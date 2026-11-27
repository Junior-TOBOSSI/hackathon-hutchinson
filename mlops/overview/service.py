"""AI Leader home page blocks (DBX-09).

Every block is built from the EXISTING services and their read caches (connector cache with
DBX-PERF-01 TTL / single-flight and the INT-GLOBAL-01 stale-while-revalidate for GET
requests). A block never raises: it returns its own ``status`` (available / partial /
unavailable / simulated), ``fetched_at`` and, when relevant, the sources that failed.
Nothing is hardcoded: managed models, dataset families, pipelines, stations and policies are
all read at run time, so new datasets / models appear without changing this module.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

BLOCK_TTL = 20  # seconds; the underlying sources keep their own caches

BLOCKS = (
    "datasets",
    "training",
    "registry",
    "infrastructure",
    "monitoring",
    "retraining",
    "activity",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat(timespec="seconds")
    return str(value)


class Partial:
    """Collects failures of independent sub-sources of one block."""

    def __init__(self) -> None:
        self.failed: list[dict[str, str]] = []

    def run(self, name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - reported, never hidden behind a default value
            self.failed.append(
                {"source": name, "detail": f"{type(exc).__name__}: {str(exc)[:160]}"}
            )
            return default


def block(name: str, fn: Callable[[Partial], dict[str, Any]]) -> dict[str, Any]:
    p = Partial()
    try:
        data = fn(p)
    except Exception as exc:  # noqa: BLE001 - one block never breaks the page
        return {
            "name": name,
            "status": "unavailable",
            "fetched_at": now_iso(),
            "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
            "failed": p.failed,
        }
    status = "partial" if p.failed else data.pop("_status", "available")
    return {
        "name": name,
        "status": status,
        "fetched_at": now_iso(),
        "data": data,
        "failed": p.failed,
    }


# --------------------------------------------------------------------------- services


def _training(c):
    from mlops.api.training_routes import service_for

    return service_for(c)


def _monitoring(c):
    from mlops.api.monitoring_routes import monitoring_for

    return monitoring_for(c)


def _store(c):
    from mlops.databricks.datasets import dataset_store

    return dataset_store(c)


def _decisions():
    from mlops.deployment.runtime import operation_store

    return operation_store()


# --------------------------------------------------------------------------- blocks


def datasets(c, p: Partial) -> dict[str, Any]:
    fams = _store(c).catalog()
    rows = [
        {
            "dataset_id": f.dataset_id,
            "name": f.name,
            "use_case": f.use_case,
            "synthetic": f.synthetic,
            "versions": f.version_count,
            "latest_version": f.latest_version,
            "latest_images": f.latest_images,
            "last_published_at": f.last_published_at,
            "drafts": f.draft_count,
        }
        for f in fams
    ]
    images = [r["latest_images"] for r in rows if r["latest_images"] is not None]
    published = {r["dataset_id"] for r in rows}
    specs = p.run("pipelines", lambda: _training(c).specs, [])
    expected = {}
    for s in specs:  # declared by a pipeline, not published: shown as EXPECTED, never counted
        for fam in s.dataset.families:
            if fam not in published:
                expected.setdefault(
                    fam, {"dataset_id": fam, "use_case": s.use_case, "pipelines": []}
                )
                expected[fam]["pipelines"].append(s.id)
    return {
        "expected": list(expected.values()),
        "families": len(rows),
        "published_versions": sum(r["versions"] for r in rows),
        # Images of the LATEST published version of each family: never a sum over versions
        # (versions share images), never a count of unique images across versions.
        "latest_images": sum(images) if len(images) == len(rows) else None,
        "drafts": sum(r["drafts"] for r in rows),
        "by_use_case": _count(rows, "use_case"),
        "items": rows,
    }


def training(c, p: Partial) -> dict[str, Any]:
    svc = _training(c)
    rows = svc.trainings()
    k = p.run("kpis", lambda: svc.kpis().model_dump(), {})
    status = _count([r.model_dump() for r in rows], "status")
    return {
        "by_status": status,
        "running": status.get("running", 0) + status.get("queued", 0),
        "kpis": k,
        "pipelines": [
            {
                "pipeline_id": v.spec.id,
                "name": v.spec.name,
                "use_case": v.spec.use_case,
                "executable": v.executable,
            }
            for v in p.run("pipelines", svc.pipelines, [])
        ],
        # Real runs only (at most the last 25 job runs per pipeline: Databricks API page).
        "runs": [
            {
                "job_run_id": r.job_run_id,
                "pipeline_id": r.pipeline_id,
                "dataset_id": r.dataset_id,
                "dataset_version": r.dataset_version,
                "status": r.status,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "duration_s": r.duration_s,
                "model_versions": r.model_versions,
            }
            for r in rows
        ],
        "scope": "last 25 job runs per pipeline (Databricks API page)",
    }


def _latest_decision(store, model_id: str, version: str) -> str | None:
    ds = [d for d in store.decisions(model_id, version) if d.status == "applied"]
    return ds[0].decision if ds else None


def registry(c, p: Partial) -> dict[str, Any]:
    store = p.run("decision journal", _decisions)
    stations = p.run("Core stations", lambda: _monitoring(c)._snapshot().stations, [])
    models = []
    for m in c.settings.models:
        st = p.run(f"registry {m.id}", lambda m=m: c.model_status(m.id))
        if st is None:
            continue
        versions = []
        for vs in st.versions:
            v = vs.version.version
            decision = _latest_decision(store, m.id, v) if store else None
            versions.append(
                {
                    "version": v,
                    "created_at": _iso(vs.version.created_at),
                    "approved": vs.approved,
                    "rejected": decision == "rejected",
                    "aliases": vs.aliases,
                    "served_by": vs.served_by,
                    "candidate": not vs.approved and not vs.aliases and decision != "rejected",
                }
            )
        # Edge: versions DECLARED by the stations (model.status). Never confused with Serving.
        edge = [
            {"station_id": s["station_id"], "simulated": bool(s.get("simulated")), **mm}
            for s in stations
            for mm in s.get("models", [])
            if mm.get("use_case") == m.argos_use_case
        ]
        models.append(
            {
                "model_id": m.id,
                "name": m.display_name,
                "use_case": m.argos_use_case,
                "uc_name": m.uc_name,
                "synthetic": m.synthetic,
                "versions": versions,
                "candidates": sum(v["candidate"] for v in versions),
                "approved": sum(v["approved"] for v in versions),
                "champion": st.aliases.get("champion"),
                "served": {k: v for k, v in st.served.items() if v},
                "edge_declared": edge,
            }
        )
    return {
        "models": models,
        "by_use_case": _count(models, "use_case"),
        "versions": sum(len(m["versions"]) for m in models),
        "candidates": sum(m["candidates"] for m in models),
        "approved": sum(m["approved"] for m in models),
        "champions": sum(1 for m in models if m["champion"]),
        "served_endpoints": sum(len(m["served"]) for m in models),
        "edge_note": "Edge versions are those declared by the stations (model.status); Databricks "
        "Serving is a separate deployment target",
    }


def infrastructure(c, p: Partial) -> dict[str, Any]:
    def check(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
        try:
            detail = fn()
            return {"name": name, "status": "available", "detail": detail}
        except Exception as exc:  # noqa: BLE001 - shown as unavailable
            return {
                "name": name,
                "status": "unavailable",
                "detail": f"{type(exc).__name__}: {str(exc)[:120]}",
            }

    ping = check(
        "databricks", lambda: c._cached("overview:ping", lambda: c.ping().model_dump(), ttl=30)
    )
    checks = [
        ping,
        check("mlflow", lambda: f"{len(c.list_experiments())} experiment(s)"),
        check(
            "unity_catalog",
            lambda: (
                f"catalog {c.settings.catalog}"
                if c.settings.catalog in c.list_catalogs()
                else f"catalog {c.settings.catalog} not visible"
            ),
        ),
    ]
    endpoints = p.run("serving endpoints", c.list_endpoints, [])
    snap = p.run("Core", lambda: _monitoring(c)._snapshot())
    stations = snap.stations if snap else []
    core_status = snap.status.status if snap else "unavailable"
    mon = p.run("monitoring coverage", lambda: _monitoring(c).models(_kind(c)), [])
    operational = [r for r in mon if r["source"] == "operational"]
    return {
        "checks": checks,
        "endpoints": [
            {"name": e.name, "ready": e.ready, "served": [(s.model, s.version) for s in e.served]}
            for e in endpoints
        ],
        "core": {
            "status": core_status,
            "detail": snap.status.detail if snap else None,
            "fetched_at": snap.status.fetched_at if snap else None,
        },
        "fleet": {
            "stations": len(stations),
            "online": sum(1 for s in stations if s.get("online")),
            "offline": sum(1 for s in stations if not s.get("online")),
            "simulated": sum(1 for s in stations if s.get("simulated")),
            "cells": len({s.get("cell") for s in stations if s.get("cell")}),
        },
        "monitoring_coverage": {
            "operational_models": len(operational),
            "with_representative_reference": sum(
                1 for r in operational if r["drift"]["status"] in ("stable", "watch", "alert")
            ),
            "registry_models_without_inference": sum(1 for r in mon if r["source"] == "registry"),
        },
    }


def _kind(c) -> str:
    """Real production when it exists, otherwise the simulation (never both mixed)."""
    real = _monitoring(c).summary("real")
    return "real" if real["inferences"] > 0 else "simulated"


def monitoring(c, p: Partial) -> dict[str, Any]:
    svc = _monitoring(c)
    kind = _kind(c)
    s = svc.summary(kind)
    rows = p.run("catalogue", lambda: svc.models(kind), [])
    states = _count([r["drift"] for r in rows], "status")
    coverage = ("reference_absent", "insufficient_reference", "insufficient_current", "mixed_data")
    data = {
        "data_kind": kind,
        "core_status": s["status"],
        "sources": s["sources"],
        "inferences": s["inferences"],
        "latency_p95": s.get("latency_p95"),
        "open_alerts": s["open_alerts"],
        "drift_alerts": s["drift_alerts"],
        "availability_alerts": s["availability_alerts"],
        "last_collection": s["last_collection"],
        "drift_states": states,
        "drift_detected": sum(states.get(k, 0) for k in ("alert", "watch")),
        "reference_absent": states.get("reference_absent", 0),
        "insufficient_coverage": sum(states.get(k, 0) for k in coverage),
        "to_investigate": sum(1 for r in rows if r.get("needs_investigation")),
        "note": "no open alert is not a proof of stability; "
        "no production accuracy without ground truth",
    }
    if kind == "simulated":
        data["_status"] = "simulated"
    return data


def retraining(c, p: Partial) -> dict[str, Any]:
    from mlops.api import retraining_routes
    from mlops.api.retraining_routes import retraining_for
    from mlops.training.service import launch_guard

    svc = retraining_for(c)
    pols = svc.store.policies()
    props = svc.store.proposals()
    last_eval = {}
    for e in svc.store.evaluations(None, 200):
        last_eval.setdefault(e.policy_id, e)
    sched = (
        retraining_routes.SCHEDULER.state() if retraining_routes.SCHEDULER else {"enabled": False}
    )
    return {
        "active": sum(1 for x in pols if x.active),
        "inactive": sum(1 for x in pols if not x.active),
        "automatic": sum(1 for x in pols if x.active and x.mode == "auto"),
        "pending_proposals": sum(1 for x in props if x.status in ("pending", "accepted")),
        "uncertain_proposals": sum(1 for x in props if x.status == "uncertain"),
        "satisfied_conditions": sum(
            sum(1 for r in e.conditions if r.state == "satisfied") for e in last_eval.values()
        ),
        "eligible_policies": sum(1 for e in last_eval.values() if e.eligible),
        "automatic_launches": sum(
            1
            for x in svc.store.ledger()
            if x["status"] == "launched"
            and any(
                pp.proposal_id == x["proposal_id"]
                and pp.decided_by in (None, "scheduler")
                and pp.mode == "auto"
                for pp in props
            )
        ),
        "scheduler": {k: sched.get(k) for k in ("enabled", "running", "last_tick")},
        "remote_lock": launch_guard(),
        "policies": [
            {
                "policy_id": x.policy_id,
                "name": x.name,
                "model_id": x.model_id,
                "active": x.active,
                "mode": x.mode,
                "version": x.version,
            }
            for x in pols
        ],
    }


def activity(c, p: Partial, limit: int = 40) -> dict[str, Any]:
    """Real dated events only, each with its source and, when it exists, a link to its detail."""
    ev: list[dict[str, Any]] = []

    def add(at, type_, source, title, detail, status, link=None):
        if at:
            ev.append(
                {
                    "at": _iso(at),
                    "type": type_,
                    "source": source,
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "link": link,
                }
            )

    for f in p.run("datasets", lambda: _store(c).catalog(), []):
        idx = p.run(f"dataset {f.dataset_id}", lambda f=f: _store(c).family_index(f.dataset_id))
        for v in idx.versions if idx else []:
            images = sum(n for split in (v.counts or {}).values() for n in split.values())
            add(
                v.created_at,
                "dataset",
                "Datasets (Unity Catalog Volume)",
                f"{f.name} {v.version} publiée",
                f"{images} images · {', '.join(v.classes)}",
                "published",
                {"section": "datasets", "dataset": f.dataset_id, "version": v.version},
            )
    for r in p.run("training", lambda: _training(c).trainings(), []):
        link = {"section": "training", "run": str(r.job_run_id)}
        add(
            r.started_at,
            "training_started",
            "Databricks Jobs",
            f"Entraînement {r.pipeline_id} lancé",
            f"{r.dataset_id or '?'} {r.dataset_version or ''}".strip(),
            "running" if r.status in ("running", "queued") else "started",
            link,
        )
        if r.ended_at and r.status in ("succeeded", "failed", "cancelled"):
            add(
                r.ended_at,
                "training_ended",
                "Databricks Jobs",
                f"Entraînement {r.pipeline_id} terminé",
                f"{r.dataset_id or '?'} {r.dataset_version or ''}".strip(),
                r.status,
                link,
            )
    store = p.run("decision journal", _decisions)
    for m in c.settings.models:
        st = p.run(f"registry {m.id}", lambda m=m: c.model_status(m.id))
        for vs in st.versions if st else []:
            v = vs.version.version
            add(
                vs.version.created_at,
                "model_version",
                "Unity Catalog",
                f"{m.uc_name} v{v} enregistrée",
                "version candidate" if not vs.approved else "version",
                "registered",
                {"section": "registry", "model": m.id},
            )
            for d in store.decisions(m.id, v) if store else []:
                add(
                    d.created_at,
                    "decision",
                    "Registre HOVIS (décisions)",
                    f"{m.uc_name} v{v} : {d.decision}",
                    d.reason,
                    d.status,
                    {"section": "registry", "model": m.id},
                )
    for op in p.run("deployments", lambda: store.list(None, 50), []) if store else []:
        add(
            op.created_at,
            op.kind,
            "Deployment Center (Databricks Serving)",
            f"{op.endpoint} → v{op.version}",
            op.reason,
            op.status,
            {"section": "deployment"},
        )
    from mlops.api.retraining_routes import retraining_for

    rsvc = p.run("retraining", lambda: retraining_for(c))
    for x in rsvc.store.proposals() if rsvc else []:
        add(
            x.created_at,
            "proposal",
            "Politiques de réentraînement",
            f"Proposition {x.pipeline_id}",
            "; ".join(x.reasons)[:160],
            x.status,
            {"section": "training", "view": "policies", "policy": x.policy_id},
        )
    for a in p.run("monitoring alerts", lambda: _monitoring(c).store.alerts(), []):
        add(
            a["first_detected"],
            "alert",
            "Monitoring MLOps",
            f"Alerte {a.get('kind')} · {a.get('indicator')}",
            a.get("model_key") or a.get("station_id"),
            a["state"],
            {"section": "monitoring"},
        )
    ev.sort(key=lambda e: e["at"], reverse=True)
    return {
        "events": ev[:limit],
        "total": len(ev),
        "not_dated": ["promotions d'alias (Unity Catalog ne date pas les changements d'alias)"],
    }


BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "datasets": datasets,
    "training": training,
    "registry": registry,
    "infrastructure": infrastructure,
    "monitoring": monitoring,
    "retraining": retraining,
    "activity": activity,
}


def build(c, name: str) -> dict[str, Any]:
    """One block, cached BLOCK_TTL s on the connector cache (single-flight, SWR on GET)."""
    builder = BUILDERS[name]
    return c._cached(
        f"overview:v2:{name}", lambda: block(name, lambda p: builder(c, p)), ttl=BLOCK_TTL
    )


def _count(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r.get(key))] = out.get(str(r.get(key)), 0) + 1
    return out
