"""Monitoring service (DBX-07B). Read-only on every source; writes only the local history
(snapshots, immutable references, alerts) through EXPLICIT collection / freeze requests.

Rules enforced here:
- inferences are deduplicated by event id; parts are counted once (distinct part id);
- an inference is linked to a Unity Catalog version ONLY through an exact package reference
  (not available yet from the Edge): otherwise it is kept as "not associated with the
  registry" (no matching by names);
- simulated and real data are never mixed silently (``data_kind``: real | simulated | all);
- a truncated Core read makes the aggregation "partial";
- human: corrections are counted per part; without recorded confirmations the number of
  verified parts is UNKNOWN, so no agreement rate is computed;
- drift = data / score drift only, never a proof of concept drift.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from mlops.monitoring import stats
from mlops.monitoring.sources import CoreSnapshot, CoreSource, DeploymentSource, SourceStatus
from mlops.monitoring.store import MonitoringStore

SCORE_BINS = [i / 20 for i in range(21)]
DECISIONS_CORE = ["conforme", "a_verifier", "anomalie"]
# Offline evaluation decisions of the Quality group (evaluer.py) mapped to the platform ones.
OFFLINE_DECISION = {"OK": "conforme", "A_VERIFIER": "a_verifier", "NOK": "anomalie"}
MAX_STORED_SCORES = 5000
MAX_ITEMS = 500


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


# --------------------------------------------------------------------------- observations


def observations(snap: CoreSnapshot) -> tuple[list[dict], list[dict], list[dict]]:
    """(inferences, parts, corrections) deduplicated by their identifiers."""
    simulated_station = {s["station_id"]: bool(s.get("simulated")) for s in snap.stations}
    seen, inferences, corrections = set(), [], {}
    for e in snap.events:
        if e.get("event_id") in seen:
            continue
        seen.add(e.get("event_id"))
        kind = e.get("event_type")
        payload = e.get("payload") or {}
        simulated = bool(e.get("simulated")) or simulated_station.get(e.get("station_id"), False)
        if kind == "inference":
            ev = payload.get("event") or {}
            inferences.append(
                {
                    "event_id": e["event_id"],
                    "station_id": e["station_id"],
                    "occurred_at": e["occurred_at"],
                    "use_case": e.get("use_case") or ev.get("use_case"),
                    "model_name": e.get("model_name") or ev.get("model_name"),
                    "model_version": str(e.get("model_version") or ev.get("model_version")),
                    "score": ev.get("score", e.get("score")),
                    "decision": e.get("decision") or ev.get("decision"),
                    "latency_ms": ev.get("latency_ms"),
                    "part_id": e.get("part_id"),
                    "cycle_id": e.get("cycle_id"),
                    "simulated": simulated,
                    # not carried by inference events yet (coordination request)
                    "package_sha256": None,
                    "inner_event_id": ev.get("event_id"),
                }
            )
            inferences[-1]["model_key"] = model_key(inferences[-1])
        elif kind == "part.corrected":
            c = payload.get("correction") or {}
            cid = c.get("correction_id") or e["event_id"]
            corrections[cid] = {**c, "station_id": e["station_id"], "simulated": simulated}
    by_inner = {i["inner_event_id"]: i for i in inferences if i.get("inner_event_id")}
    parts, seen_parts = [], set()
    for p in snap.parts:
        if p["part_id"] in seen_parts:
            continue
        seen_parts.add(p["part_id"])
        pred = p.get("prediction") or {}
        # Exact link part -> inference through the inference event id (never by names).
        inf = by_inner.get(pred.get("event_id")) if pred else None
        parts.append(
            {
                **p,
                "simulated": simulated_station.get(p["station_id"], False),
                "model_key": inf["model_key"] if inf else None,
                "use_case": inf["use_case"] if inf else None,
                "model_version": str(pred["model_version"]) if pred.get("model_version") else None,
            }
        )
    by_part = {p["part_id"]: p for p in parts}
    for c in corrections.values():
        p = by_part.get(c.get("part_id")) or {}
        c.update(
            model_key=p.get("model_key"),
            use_case=p.get("use_case"),
            model_version=p.get("model_version"),
            ai_initial=p.get("predicted_verdict"),
        )
    return inferences, parts, list(corrections.values())


def model_key(inf: dict) -> str:
    # Exact registry link needs a package reference; none yet -> explicitly unassociated.
    return f"unassociated:{inf['use_case']}:{inf['model_name']}"


def select(
    rows: list[dict],
    *,
    data_kind: str = "all",
    station: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    key: str | None = None,
    version: str | None = None,
    use_case: str | None = None,
    time_field: str = "occurred_at",
) -> list[dict]:
    out = []
    for r in rows:
        if data_kind == "real" and r.get("simulated"):
            continue
        if data_kind == "simulated" and not r.get("simulated"):
            continue
        if station and r.get("station_id") != station:
            continue
        t = _ts(r.get(time_field))
        if start and (t is None or t < start):
            continue
        if end and (t is None or t >= end):
            continue
        if key and r.get("model_key") != key:
            continue
        if use_case and r.get("use_case") != use_case:
            continue
        if version and r.get("model_version") != version:
            continue
        out.append(r)
    return out


def aggregate(
    infs: list[dict], start: datetime | None = None, end: datetime | None = None
) -> dict[str, Any]:
    scores = [float(i["score"]) for i in infs if i.get("score") is not None]
    lat = [float(i["latency_ms"]) for i in infs if i.get("latency_ms") is not None]
    times = sorted(t for t in (_ts(i["occurred_at"]) for i in infs) if t)
    span_h = (
        (end - start).total_seconds()
        if start and end
        else (times[-1] - times[0]).total_seconds()
        if len(times) > 1
        else 0
    ) / 3600
    decisions = Counter(i.get("decision") for i in infs)
    n = len(infs)
    return {
        "n_inferences": n,
        "n_parts": len(
            {
                i.get("part_id") or f"{i.get('station_id')}:{i.get('cycle_id')}"
                for i in infs
                if i.get("part_id") or i.get("cycle_id")
            }
        ),
        "cadence_per_hour": (n / span_h) if span_h > 0 else None,
        "score_mean": sum(scores) / len(scores) if scores else None,
        "score_histogram": {
            "edges": SCORE_BINS,
            "counts": stats.histogram(scores, [-1e-9, *SCORE_BINS[1:-1], 1 + 1e-9]),
        },
        "decision_counts": {d: decisions.get(d, 0) for d in DECISIONS_CORE},
        "decision_rates": {d: (decisions.get(d, 0) / n if n else None) for d in DECISIONS_CORE},
        "latency_ms": {
            "mean": sum(lat) / len(lat) if lat else None,
            "p50": stats.quantile(lat, 0.5),
            "p95": stats.quantile(lat, 0.95),
        },
        "last_activity": times[-1].isoformat() if times else None,
        "first_activity": times[0].isoformat() if times else None,
        "simulated": sorted({bool(i.get("simulated")) for i in infs}),
    }


def human(parts: list[dict], corrections: list[dict]) -> dict[str, Any]:
    """Per PART: AI initial prediction kept, last correction = current human verdict."""
    by_part: dict[str, list[dict]] = defaultdict(list)
    for c in corrections:
        by_part[c["part_id"]].append(c)
    ai = {p["part_id"]: p.get("predicted_verdict") for p in parts}
    false_rejects = missed = 0
    types: Counter = Counter()
    for pid, cs in by_part.items():
        cs.sort(key=lambda c: c.get("sequence", 0))
        final, initial = cs[-1].get("new_verdict"), ai.get(pid)
        types[f"{initial}->{final}"] += 1
        false_rejects += initial == "NOK" and final == "OK"
        missed += initial == "OK" and final == "NOK"
    return {
        "corrected_parts": len(by_part),
        "corrections": len(corrections),
        "correction_types": dict(types),
        "false_rejects_observed": false_rejects,
        "missed_defects_observed": missed,
        "physical_inspections": sum(1 for c in corrections if c.get("physical_inspection")),
        "verified_parts": None,
        "agreement_rate": None,
        "agreement_status": "unavailable: the Core records corrections only, "
        "not confirmations without "
        "correction, so the number of verified parts (denominator) is unknown",
        "warning": "Observed disagreements are NOT a production accuracy.",
        "items": [
            {
                k: c.get(k)
                for k in (
                    "correction_id",
                    "at",
                    "station_id",
                    "part_id",
                    "sequence",
                    "model_key",
                    "model_version",
                    "ai_initial",
                    "previous_verdict",
                    "new_verdict",
                    "reason",
                    "physical_inspection",
                    "actor_role",
                    "simulated",
                )
            }
            for c in sorted(corrections, key=lambda c: str(c.get("at")), reverse=True)[:MAX_ITEMS]
        ],
    }


# --------------------------------------------------------------------------- service


class MonitoringService:
    def __init__(
        self,
        connector=None,
        core: CoreSource | None = None,
        store: MonitoringStore | None = None,
        thresholds: stats.Thresholds | None = None,
        training=None,
        deployment: DeploymentSource | None = None,
    ) -> None:
        self.c = connector
        self.core = core or CoreSource()
        self.store = store or MonitoringStore()
        self.t = thresholds or stats.Thresholds()
        self._training = training
        self.deployment = deployment or DeploymentSource()

    @property
    def training(self):
        if self._training is None and self.c is not None:
            from mlops.api.training_routes import service_for

            self._training = service_for(self.c)
        return self._training

    def _snapshot(self) -> CoreSnapshot:
        if self.c is not None:
            return self.c._cached("monitoring:core", self.core.snapshot, ttl=30)
        return self.core.snapshot()

    # ------------------------------------------------------------------ operational

    def operational(
        self,
        *,
        data_kind="all",
        station=None,
        key=None,
        version=None,
        start=None,
        end=None,
        use_case=None,
    ) -> dict[str, Any]:
        snap = self._snapshot()
        infs, parts, corrections = observations(snap)
        f = {
            "data_kind": data_kind,
            "station": station,
            "key": key,
            "version": version,
            "use_case": use_case,
            "start": start,
            "end": end,
        }
        sel = select(infs, **f)
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for i in sel:
            groups[(model_key(i), i["model_version"], i["station_id"])].append(i)
        sel_parts = select(parts, **f, time_field="created_at")
        errors = Counter((p.get("error") or {}).get("code") for p in sel_parts if p.get("error"))
        return {
            "status": "unavailable"
            if snap.status.status == "unavailable"
            else ("partial" if snap.status.status == "partial" else "available"),
            "sources": [snap.status.__dict__],
            "data_kind": data_kind,
            "total": aggregate(sel, start, end),
            "groups": [
                {
                    "model_key": k,
                    "model_version": v,
                    "station_id": s,
                    "registry_link": "not associated with the registry",
                    **aggregate(rows, start, end),
                }
                for (k, v, s), rows in sorted(groups.items())
            ],
            "parts": {
                "n_parts": len(sel_parts),
                "with_inference_error": sum(errors.values()),
                "error_codes": dict(errors),
                "note": "errors observed on parts (Core parts API); "
                "errors without a part are not reported by the Core; with a model filter, "
                "only parts linked to an inference of that model are counted",
            },
            "model_states": [
                {
                    "station_id": s["station_id"],
                    "cell": s.get("cell"),
                    "simulated": s.get("simulated"),
                    "online": s.get("online"),
                    "last_seen_at": s.get("last_seen_at"),
                    "models": s.get("models", []),
                    "equipment": [
                        e
                        for e in s.get("equipment", [])
                        if e.get("equipment_type") == "model_runtime"
                    ],
                }
                for s in snap.stations
                if not station or s["station_id"] == station
            ],
            "human": human(sel_parts, select(corrections, **f, time_field="at")),
        }

    # ------------------------------------------------------------------ offline (MLflow)

    def performance(self, model_id: str) -> dict[str, Any]:
        tr = self.training
        status = self.c.model_status(model_id)
        rows = []
        for vs in status.versions:
            run_id = vs.version.run_id
            if not run_id:
                continue
            run = self.c.get_run(run_id)
            m, tags = run.metrics, run.tags
            ds_id = tags.get("argos.dataset_id") or (
                "quality-synthetic" if model_id == "quality-poc" else None
            )
            ds_v = tags.get("argos.dataset_version") or run.params.get("dataset_version")
            fp = None
            if ds_id and ds_v:
                try:
                    summary = tr.resolver.summary(ds_id, ds_v)
                    fp = summary.split_fingerprints.get("test") if summary else None
                except Exception:  # noqa: BLE001 - shown as unknown comparability
                    fp = None
            ev = tr.evaluation(run_id)
            rows.append(
                {
                    "version": vs.version.version,
                    "run_id": run_id,
                    "approved": vs.approved,
                    "aliases": vs.aliases,
                    "dataset": {"id": ds_id, "version": ds_v, "test_fingerprint": fp},
                    "metrics": {
                        "accuracy": m.get("test_accuracy"),
                        "precision_nok": m.get("test_precision_nok"),
                        "recall_nok": m.get("test_rappel", m.get("test_recall_nok")),
                        "f1_nok": m.get("test_f1_nok"),
                        "false_rejects": m.get("test_faux_rejets"),
                        "missed_defects": m.get("test_nok_declarees_ok"),
                        "latency_ms_mean": m.get("test_latence_ms_moyenne"),
                        "latency_ms_p95": m.get("test_latence_ms_p95"),
                        "n_test": m.get("test_n_photos"),
                    },
                    "per_class": ev.get("per_class") if ev.get("available") else None,
                    "confusion": {"columns": ev.get("columns"), "matrix": ev.get("matrix")}
                    if ev.get("available")
                    else None,
                    "synthetic": tags.get("synthetic") == "true"
                    or (ds_id or "").startswith("quality-synthetic"),
                    **_representativeness(m.get("test_n_photos"), self.t.min_reference),
                }
            )
        groups = defaultdict(list)
        for r in rows:
            groups[r["dataset"]["test_fingerprint"] or f"unknown:{r['version']}"].append(
                r["version"]
            )
        return {
            "model_id": model_id,
            "scope": "offline evaluation on the test split, not a production measure",
            "versions": rows,
            "comparable_groups": [v for v in groups.values()],
        }

    # ------------------------------------------------------------------ references

    def offline_reference(self, model_id: str, version: str) -> dict[str, Any]:
        """Build (and store, immutable) a reference from the version's offline test predictions."""
        status = self.c.model_status(model_id)
        vs = next((v for v in status.versions if v.version.version == version), None)
        if vs is None or not vs.version.run_id:
            raise LookupError(f"{model_id} v{version} has no run")
        run_id = vs.version.run_id
        raw = self.training._artifact(run_id, "evaluation/predictions.csv")
        if raw is None:
            raise LookupError(
                "no per-image predictions for this version: offline reference unavailable"
            )
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        run = self.c.get_run(run_id)
        return self._save_reference(
            {
                "source": "offline_test",
                "model_key": f"registry:{model_id}",
                "model_version": version,
                "run_id": run_id,
                "package_sha256": None,
                "window": None,
                "scores": [float(r["score_nok"]) for r in rows if r.get("score_nok")],
                "latencies": [float(r["latence_ms"]) for r in rows if r.get("latence_ms")],
                "decisions": Counter(
                    OFFLINE_DECISION.get(r["verdict"], r["verdict"]) for r in rows
                ),
                "score_definition": f"{model_id}: "
                "score_nok = P(NOK_SANS) + P(NOK_DOUBLE) (qualite702)",
                "fingerprints": {
                    "manifest_sha256": run.tags.get("argos.manifest_sha256"),
                    "test_split": run.tags.get("hovis.split_fingerprint.test"),
                },
                "synthetic": True
                if (run.tags.get("argos.dataset_id") or "").startswith("quality-synthetic")
                or run.tags.get("synthetic") == "true"
                else None,
            }
        )

    def operational_reference(
        self, key: str, version: str, start: datetime, end: datetime, data_kind: str
    ) -> dict[str, Any]:
        if data_kind == "all":
            raise ValueError("a reference must be either real or simulated data, not both")
        infs, _, _ = observations(self._snapshot())
        sel = select(infs, data_kind=data_kind, key=key, version=version, start=start, end=end)
        return self._save_reference(
            {
                "source": "operational_window",
                "model_key": key,
                "model_version": version,
                "run_id": None,
                "package_sha256": None,
                "window": {"start": start.isoformat(), "end": end.isoformat()},
                "scores": [float(i["score"]) for i in sel if i.get("score") is not None],
                "latencies": [
                    float(i["latency_ms"]) for i in sel if i.get("latency_ms") is not None
                ],
                "decisions": Counter(i.get("decision") for i in sel),
                "score_definition": f"{key}: Core inference score",
                "fingerprints": {},
                "synthetic": data_kind == "simulated",
            }
        )

    def _save_reference(self, r: dict) -> dict[str, Any]:
        basis = json.dumps(
            {k: r[k] for k in ("source", "model_key", "model_version", "run_id", "window")},
            sort_keys=True,
        )
        ref = {
            **{k: v for k, v in r.items() if k not in ("scores", "latencies", "decisions")},
            "reference_id": hashlib.sha256(basis.encode()).hexdigest()[:16],
            "created_at": now_iso(),
            "n": len(r["scores"]),
            "edges": stats.reference_edges(r["scores"]) if r["scores"] else None,
            "scores": r["scores"][:MAX_STORED_SCORES],
            "latencies": r["latencies"][:MAX_STORED_SCORES],
            "decision_counts": dict(r["decisions"]),
            "representative": len(r["scores"]) >= self.t.min_reference,
            "warnings": []
            if len(r["scores"]) >= self.t.min_reference
            else [
                f"only {len(r['scores'])} observations (< {self.t.min_reference}): "
                "not representative, no reliable alert"
            ],
        }
        ref["edges"] = (
            [None if math.isinf(e) else e for e in ref["edges"]]  # JSON has no infinity
            if ref["edges"]
            else None
        )
        self.store.add_reference(ref["reference_id"], ref["model_key"], ref["created_at"], ref)
        return ref

    # ------------------------------------------------------------------ drift

    def drift(
        self,
        reference: dict,
        population: list[dict],
        population_key: str,
        population_version: str,
        population_simulated: bool,
        score_definition: str,
    ) -> dict[str, Any]:
        reasons = []
        if reference["model_key"] != population_key or str(reference["model_version"]) != str(
            population_version
        ):
            reasons.append("reference belongs to another model / version")
        if reference["score_definition"] != score_definition:
            reasons.append("incompatible score definitions")
        if (
            reference.get("synthetic") is not None
            and bool(reference["synthetic"]) != population_simulated
        ):
            reasons.append("synthetic / simulated data compared with real data")
        base = {
            "reference_id": reference["reference_id"],
            "reference_source": reference.get("source"),
            "reference_representative": reference.get("representative"),
            "reference_warnings": reference.get("warnings", []),
            "n_reference": reference["n"],
            "n_current": len(population),
            "thresholds": asdict(self.t),
            "histogram": _histograms(reference, population),
        }
        if reasons:
            return {**base, "status": "incompatible", "reasons": reasons}
        if reference["n"] < self.t.min_reference:
            return {**base, "status": "insufficient_reference"}
        if len(population) < self.t.min_current:
            return {**base, "status": "insufficient_current"}
        edges = [
            (-float("inf") if i == 0 else float("inf")) if e is None else e
            for i, e in enumerate(reference["edges"])
        ]
        scores = [float(p["score"]) for p in population if p.get("score") is not None]
        score_psi = stats.psi(reference["scores"], scores, edges)
        dec = Counter(p.get("decision") for p in population)
        dec_psi = stats.categorical_psi(reference["decision_counts"], dict(dec))
        lat = [float(p["latency_ms"]) for p in population if p.get("latency_ms") is not None]
        ref_lat = reference.get("latencies") or []
        shift = (
            (sum(lat) / len(lat)) / (sum(ref_lat) / len(ref_lat)) - 1
            if lat and ref_lat and sum(ref_lat)
            else None
        )
        return {
            **base,
            "status": "available",
            "measures": [
                {
                    "indicator": "score",
                    "method": "psi",
                    "value": score_psi,
                    "threshold": self.t.psi_alert,
                    "level": stats.level(score_psi, self.t),
                },
                {"indicator": "score", "method": "ks", **stats.ks(reference["scores"], scores)},
                {
                    "indicator": "decision_rate",
                    "method": "psi",
                    "value": dec_psi,
                    "threshold": self.t.psi_alert,
                    "level": stats.level(dec_psi, self.t),
                },
                {
                    "indicator": "decision_rate",
                    "method": "chi2",
                    **stats.chi2(reference["decision_counts"], dict(dec)),
                },
                {
                    "indicator": "latency",
                    "method": "mean_shift",
                    "value": shift,
                    "threshold": self.t.latency_shift_ratio,
                    "level": "unavailable"
                    if shift is None
                    else "alert"
                    if shift >= self.t.latency_shift_ratio
                    else "stable",
                },
            ],
            "note": "data / score drift only: not a proof of concept drift",
        }

    # ------------------------------------------------------------------ explicit collection

    def collect(self) -> dict[str, Any]:
        """Explicit, idempotent: recompute daily snapshots of the observed days (late events
        reconciled), evaluate alerts (one per persistent drift), log the collection."""
        at = now_iso()
        snap = self.core.snapshot()
        infs, parts, corrections = observations(snap)
        partial = snap.status.status == "partial"
        written, open_keys = 0, set()
        for kind in ("real", "simulated"):
            rows = select(infs, data_kind=kind)
            for (key, version), group in _group(
                rows, lambda i: (model_key(i), i["model_version"])
            ).items():
                for day, day_rows in _group(group, lambda i: i["occurred_at"][:10]).items():
                    start = datetime.fromisoformat(day).replace(tzinfo=UTC)
                    self.store.upsert_snapshot(
                        f"{key}|{version}|*",
                        start.isoformat(),
                        (start + timedelta(days=1)).isoformat(),
                        kind,
                        at,
                        partial,
                        aggregate(day_rows, start, start + timedelta(days=1)),
                    )
                    written += 1
                # Current population = the latest observed day (all stations of this version).
                last_day = max(i["occurred_at"][:10] for i in group)
                current = [i for i in group if i["occurred_at"][:10] == last_day]
                for ref in reversed(self.store.references(key)):
                    if str(ref["model_version"]) != str(version):
                        continue
                    result = self.drift(
                        ref,
                        current,
                        key,
                        version,
                        kind == "simulated",
                        f"{key}: Core inference score",
                    )
                    for m in result.get("measures", []):
                        if m.get("level") == "alert":
                            akey = f"{key}|{version}|*|{kind}|{m['indicator']}|{m['method']}"
                            open_keys.add(akey)
                            self.store.upsert_alert(
                                akey,
                                key,
                                at,
                                {
                                    "model_key": key,
                                    "model_version": version,
                                    "scope": "all stations",
                                    "data_kind": kind,
                                    "indicator": m["indicator"],
                                    "method": m["method"],
                                    "value": m["value"],
                                    "threshold": m["threshold"],
                                    "n": len(current),
                                    "window_day": last_day,
                                    "reference_id": ref["reference_id"],
                                    "kind": "drift",
                                },
                            )
                    break
        for s in snap.stations:
            for eq in s.get("equipment", []):
                if eq.get("equipment_type") == "model_runtime" and eq.get("status") in (
                    "down",
                    "degraded",
                ):
                    akey = f"station:{s['station_id']}|runtime|{eq.get('equipment_id')}"
                    open_keys.add(akey)
                    self.store.upsert_alert(
                        akey,
                        "availability",
                        at,
                        {
                            "kind": "availability",
                            "station_id": s["station_id"],
                            "indicator": "model_runtime",
                            "value": eq.get("status"),
                            "simulated": s.get("simulated"),
                        },
                    )
        resolved = (
            self.store.resolve_missing(open_keys, at) if snap.status.status != "unavailable" else 0
        )
        summary = {
            "sources": [snap.status.__dict__],
            "snapshots_written": written,
            "open_alerts": len(open_keys),
            "resolved_alerts": resolved,
            "partial": partial,
            "inferences": len(infs),
            "corrections": len(corrections),
        }
        self.store.log_collection(uuid.uuid4().hex, at, summary)
        return {"collected_at": at, **summary}

    # ------------------------------------------------------------------ catalogue / summary

    def drift_status(self, key: str, version: str, rows: list[dict]) -> dict[str, Any]:
        """Monitoring state of one (model key, version) against its latest stored reference,
        WITHOUT writing anything. Distinguishes absent / insufficient / incompatible / levels."""
        refs = [r for r in self.store.references(key) if str(r["model_version"]) == str(version)]
        if not refs:
            return {"status": "reference_absent", "version": version}
        kinds = {bool(r.get("simulated")) for r in rows}
        if len(kinds) > 1:
            return {
                "status": "mixed_data",
                "version": version,
                "reason": "filter real or simulated data to evaluate the drift",
            }
        result = self.drift(
            refs[-1], rows, key, version, kinds == {True}, f"{key}: Core inference score"
        )
        if result["status"] != "available":
            return {
                "status": result["status"],
                "version": version,
                "reasons": result.get("reasons", []),
                "reference_id": result["reference_id"],
                "n_reference": result["n_reference"],
                "n_current": result["n_current"],
            }
        levels = [
            m["level"] for m in result["measures"] if m.get("level") in ("alert", "watch", "stable")
        ]
        level = "alert" if "alert" in levels else "watch" if "watch" in levels else "stable"
        return {
            "status": level,
            "version": version,
            "reference_id": result["reference_id"],
            "n_reference": result["n_reference"],
            "n_current": result["n_current"],
        }

    def models(
        self, data_kind: str = "all", *, use_case=None, station=None, start=None, end=None
    ) -> list[dict[str, Any]]:
        """Catalogue: operational keys observed in the Core (NOT associated with the registry)
        and registered models (no inference associated until an exact package reference)."""
        snap = self._snapshot()
        infs, parts, corrections = observations(snap)
        f = {
            "data_kind": data_kind,
            "station": station,
            "use_case": use_case,
            "start": start,
            "end": end,
        }
        sel = select(infs, **f)
        sel_corr = select(corrections, **f, time_field="at")
        alerts = self.store.alerts("open")
        rows: list[dict] = []
        for key, group in sorted(_group(sel, lambda i: i["model_key"]).items()):
            agg = aggregate(group, start, end)
            by_version = _group(group, lambda i: i["model_version"])
            latest = max(by_version, key=lambda v: max(i["occurred_at"] for i in by_version[v]))
            rows.append(
                {
                    "model_key": key,
                    "source": "operational",
                    "name": group[0]["model_name"],
                    "use_case": group[0]["use_case"],
                    "registry_link": "not associated with the registry",
                    "versions": sorted(by_version),
                    "stations": sorted({i["station_id"] for i in group}),
                    "n_inferences": agg["n_inferences"],
                    "n_parts": agg["n_parts"],
                    "latency_p95": agg["latency_ms"]["p95"],
                    "last_activity": agg["last_activity"],
                    "simulated": agg["simulated"],
                    "corrections": sum(1 for c in sel_corr if c.get("model_key") == key),
                    "drift": self.drift_status(key, latest, by_version[latest]),
                }
            )
        if self.c is not None:
            for m in self.c.settings.models:
                if use_case and m.argos_use_case != use_case:
                    continue
                rows.append(
                    {
                        "model_key": f"registry:{m.id}",
                        "source": "registry",
                        "name": m.display_name,
                        "use_case": m.argos_use_case,
                        "registry_link": m.uc_name,
                        "model_id": m.id,
                        "versions": [],
                        "stations": [],
                        "n_inferences": 0,
                        "n_parts": 0,
                        "latency_p95": None,
                        "last_activity": None,
                        "simulated": [],
                        "corrections": 0,
                        "synthetic": m.synthetic,
                        "drift": {"status": "no_production_data"},
                        "note": "no production inference associated with this registered model",
                    }
                )
        for r in rows:
            r["open_alerts"] = sum(1 for a in alerts if a["model_key"] == r["model_key"])
            r["references"] = len(self.store.references(r["model_key"]))
            r["needs_investigation"] = bool(r["open_alerts"]) or r["drift"]["status"] in (
                "alert",
                "watch",
            )
        return rows

    def summary(self, data_kind: str = "all") -> dict[str, Any]:
        op = self.operational(data_kind=data_kind)
        alerts = self.store.alerts("open")
        last = self.store.collections(1)
        return {
            "status": op["status"],
            "sources": op["sources"],
            "data_kind": data_kind,
            "models_monitored": len({g["model_key"] for g in op["groups"]}),
            "stations": len(op["model_states"]),
            "stations_online": sum(1 for s in op["model_states"] if s.get("online")),
            "inferences": op["total"]["n_inferences"],
            "parts": op["parts"]["n_parts"],
            "open_alerts": len(alerts),
            "drift_alerts": sum(1 for a in alerts if a.get("kind") == "drift"),
            "availability_alerts": sum(1 for a in alerts if a.get("kind") == "availability"),
            "last_collection": last[0]["at"] if last else None,
            "simulated_only": op["total"]["simulated"] == [True],
            "latency_p95": op["total"]["latency_ms"]["p95"],
        }

    # ------------------------------------------------------------------ DBX-08 signals (read-only)

    def retraining_signals(self, model_id: str, policy: Any | None) -> dict[str, Any]:
        key = f"registry:{model_id}"
        persistent = [
            a
            for a in self.store.alerts("open")
            if a["model_key"] == key and a["first_detected"] != a["last_detected"]
        ]
        validated = None
        try:
            status = self.c.model_status(model_id)
            latest = status.versions[-1] if status.versions else None
            run = (
                self.c.get_run(latest.version.run_id) if latest and latest.version.run_id else None
            )
            ds_id = (run.tags.get("argos.dataset_id") if run else None) or (
                "quality-synthetic" if model_id == "quality-poc" else None
            )
            ds_v = (run.tags.get("argos.dataset_version") if run else None) or (
                run.params.get("dataset_version") if run else None
            )
            if ds_id and ds_v:
                idx = self.training.resolver.store.family_index(ds_id)
                after = False
                total = 0
                for v in idx.versions:
                    if after and v.changes:
                        total += (
                            v.changes.get("validated", 0)
                            + v.changes.get("corrected", 0)
                            + v.changes.get("imported", 0)
                        )
                    after = after or v.version == ds_v
                validated = {
                    "dataset_id": ds_id,
                    "trained_on": ds_v,
                    "new_validated_annotations": total,
                }
        except Exception as exc:  # noqa: BLE001 - signal reported as unavailable
            validated = {"status": "unavailable", "detail": type(exc).__name__}
        raw = human(*observations(self._snapshot())[1:])
        conditions = {
            "persistent_drift": {
                "met": bool(persistent),
                "alerts": len(persistent),
                "threshold": getattr(policy, "max_drift_alerts", None),
            },
            "new_validated_annotations": {
                **(validated or {"status": "unavailable"}),
                "threshold": getattr(policy, "min_new_labels", None),
                "raw_core_corrections": raw["corrections"],
                "note": "raw Core corrections are not validated training annotations",
            },
            "performance_degradation": {
                "met": False,
                "status": "not measurable: no labelled production sample",
            },
            "schedule": {
                "met": False,
                "cron": getattr(policy, "schedule_cron", None),
                "status": "no scheduler (DBX-08)",
            },
            "manual_request": {"met": False, "status": "no manual request recorded"},
        }
        n = conditions["new_validated_annotations"].get("new_validated_annotations")
        thr = conditions["new_validated_annotations"]["threshold"]
        conditions["new_validated_annotations"]["met"] = bool(n is not None and thr and n >= thr)
        return {
            "model_id": model_id,
            "eligible": any(c.get("met") for c in conditions.values()),
            "conditions": conditions,
            "action": "none: read-only evaluation; approval and deployment stay human decisions",
        }


def _representativeness(n_test: float | None, minimum: int) -> dict[str, Any]:
    if n_test is None:
        return {
            "representative": None,
            "warnings": ["test size unknown: representativeness unknown"],
        }
    if n_test < minimum:
        return {
            "representative": False,
            "warnings": [f"test of {int(n_test)} images (< {minimum}): not representative"],
        }
    return {"representative": True, "warnings": []}


def _histograms(reference: dict, population: list[dict]) -> dict[str, Any] | None:
    """Reference and current score distributions on the SAME reference edges (proportions)."""
    if not reference.get("edges") or not reference.get("scores"):
        return None
    edges = [
        (-math.inf if i == 0 else math.inf) if e is None else e
        for i, e in enumerate(reference["edges"])
    ]
    cur = [float(p["score"]) for p in population if p.get("score") is not None]
    ref_counts = stats.histogram(reference["scores"], edges)
    cur_counts = stats.histogram(cur, edges)
    return {
        "edges": reference["edges"],
        "reference_counts": ref_counts,
        "current_counts": cur_counts,
        "reference": [c / len(reference["scores"]) for c in ref_counts],
        "current": [c / len(cur) for c in cur_counts] if cur else None,
    }


def _group(rows: list[dict], key) -> dict:
    out: dict = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


def source_block(name: str, fn) -> dict[str, Any]:
    """Overview v2 block: own status and freshness, never fails the whole page."""
    try:
        data = fn()
        return {"name": name, "status": "available", "fetched_at": now_iso(), "data": data}
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name,
            "status": "unavailable",
            "fetched_at": now_iso(),
            "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


_ = SourceStatus  # re-exported type
