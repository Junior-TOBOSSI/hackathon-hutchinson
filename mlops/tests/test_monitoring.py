"""DBX-07B monitoring: statistics, aggregation honesty, references, drift, history, alerts and
routes. Fakes only: no Databricks, no warehouse, no network."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.monitoring import stats
from mlops.monitoring.service import MonitoringService, aggregate, human, observations, select
from mlops.monitoring.sources import CORE_LIMIT, CoreSnapshot, CoreSource, SourceStatus
from mlops.monitoring.store import MonitoringStore

KEY = "unassociated:quality:argos-demo-quality"
T0 = datetime(2026, 11, 20, 8, tzinfo=UTC)


# --------------------------------------------------------------------------- fakes


def inference(
    i,
    score,
    *,
    station="WS-01",
    version="1",
    sim=True,
    at=None,
    latency=20.0,
    decision=None,
    eid=None,
):
    at = at or T0 + timedelta(minutes=i)
    decision = decision or (
        "anomalie" if score >= 0.7 else "a_verifier" if score >= 0.4 else "conforme"
    )
    return {
        "event_id": eid or f"e-{station}-{version}-{i}-{score}",
        "event_type": "inference",
        "station_id": station,
        "occurred_at": at.isoformat().replace("+00:00", "Z"),
        "simulated": sim,
        "use_case": "quality",
        "model_name": "argos-demo-quality",
        "model_version": version,
        "score": score,
        "decision": decision,
        "cycle_id": f"C-{station}-{i}",
        "part_id": None,
        "payload": {"event": {"score": score, "latency_ms": latency, "decision": decision}},
    }


def correction(part, seq, new, cid=None, at=None):
    return {
        "event_id": f"ce-{cid or (part + str(seq))}",
        "event_type": "part.corrected",
        "station_id": "WS-01",
        "occurred_at": (at or T0).isoformat(),
        "simulated": True,
        "payload": {
            "correction": {
                "correction_id": cid or f"{part}-{seq}",
                "part_id": part,
                "sequence": seq,
                "new_verdict": new,
                "physical_inspection": True,
                "at": (at or T0).isoformat(),
            }
        },
    }


def part(pid, predicted, station="WS-01", error=None):
    return {
        "part_id": pid,
        "station_id": station,
        "created_at": T0.isoformat(),
        "predicted_verdict": predicted,
        "error": error,
        "effective_verdict": predicted,
    }


def station(sid="WS-01", sim=True, runtime="ok"):
    return {
        "station_id": sid,
        "cell": None,
        "simulated": sim,
        "online": True,
        "last_seen_at": T0.isoformat(),
        "models": [],
        "equipment": [
            {"equipment_type": "model_runtime", "equipment_id": f"rt-{sid}", "status": runtime}
        ],
    }


class FakeCore:
    def __init__(self, events=(), parts=(), stations=None, status="available", truncated=()):
        self.events, self.parts = list(events), list(parts)
        self.stations = stations if stations is not None else [station()]
        self.status, self.truncated = status, list(truncated)
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        if self.status == "unavailable":
            return CoreSnapshot(status=SourceStatus("core", "unavailable", detail="down"))
        return CoreSnapshot(
            self.stations,
            list(self.events),
            list(self.parts),
            self.truncated,
            SourceStatus("core", self.status, T0.isoformat()),
        )


def svc(tmp_path, core, **kw):
    return MonitoringService(None, core, MonitoringStore(tmp_path / "m.sqlite"), **kw)


def scores(n, mu, seed=1):
    r = random.Random(seed)
    return [min(max(r.gauss(mu, 0.08), 0.0), 1.0) for _ in range(n)]


def op_reference(s, n=150, mu=0.2, version="1", sim=True, day=0):
    """Freeze an operational reference from a window holding n inferences."""
    start = T0 + timedelta(days=day)
    s.core.events += [
        inference(i, x, version=version, sim=sim, at=start + timedelta(seconds=i))
        for i, x in enumerate(scores(n, mu))
    ]
    return s.operational_reference(
        KEY, version, start, start + timedelta(hours=1), "simulated" if sim else "real"
    )


# --------------------------------------------------------------------------- statistics


def test_psi_identical_distributions_is_zero_and_shift_is_alert():
    ref = scores(500, 0.2)
    assert stats.psi(ref, ref) == pytest.approx(0.0, abs=1e-12)
    assert stats.level(stats.psi(ref, scores(500, 0.6, seed=2)), stats.Thresholds()) == "alert"


def test_psi_known_value_from_counts():
    # (0.5-0.25)ln(0.5/0.25) + (0.5-0.75)ln(0.5/0.75)
    expected = 0.25 * math.log(2) - 0.25 * math.log(2 / 3)
    assert stats.psi_from_counts([25, 75], [50, 50]) == pytest.approx(expected)


def test_psi_empty_bins_are_smoothed_not_infinite():
    value = stats.psi_from_counts([100, 0], [0, 100])
    assert math.isfinite(value) and value > 1
    assert stats.EPSILON == 1e-4


def test_reference_edges_are_open_and_reused_for_the_population():
    edges = stats.reference_edges(scores(200, 0.3))
    assert edges[0] == -math.inf and edges[-1] == math.inf
    assert sum(stats.histogram([-5, 0.3, 7], edges)) == 3  # out-of-range values still counted


def test_ks_detects_shift_on_raw_observations():
    same = stats.ks(scores(300, 0.2), scores(300, 0.2, seed=3))
    shifted = stats.ks(scores(300, 0.2), scores(300, 0.5, seed=3))
    assert same["p_value"] > 0.01 and shifted["p_value"] < 1e-6


def test_chi2_applicable_only_when_expected_counts_reach_five():
    assert stats.chi2({"a": 2, "b": 3}, {"a": 3, "b": 2})["applicable"] is False
    assert stats.chi2({"a": 0, "b": 30}, {"a": 0, "b": 30})["applicable"] is False  # empty category
    ok = stats.chi2({"a": 50, "b": 50}, {"a": 80, "b": 20})
    assert ok["applicable"] and ok["p_value"] < 0.001 and ok["dof"] == 1


# --------------------------------------------------------------------------- aggregation honesty


def test_duplicate_events_are_counted_once(tmp_path):
    e = inference(1, 0.1)
    s = svc(tmp_path, FakeCore([e, dict(e), dict(e)]))
    assert s.operational()["total"]["n_inferences"] == 1


def test_truncated_core_read_is_reported_partial_never_exhaustive(tmp_path):
    s = svc(tmp_path, FakeCore([inference(1, 0.1)], status="partial", truncated=["WS-01"]))
    assert s.operational()["status"] == "partial"
    assert s.collect()["partial"] is True
    assert all(r["partial"] for r in s.store.snapshots())


def test_core_source_flags_truncation(monkeypatch):
    core = CoreSource("http://core")
    pages = {"/api/v1/stations": [station()]}

    def fake_get(path):
        if path in pages:
            return pages[path]
        return [inference(i, 0.1) for i in range(CORE_LIMIT)] if "events" in path else []

    monkeypatch.setattr(core, "_get", fake_get)
    snap = core.snapshot()
    assert snap.status.status == "partial" and snap.truncated_stations == ["WS-01"]


def test_unavailable_core_is_reported_and_does_not_resolve_alerts(tmp_path):
    s = svc(tmp_path, FakeCore(stations=[station(runtime="down")]))
    s.collect()
    assert len(s.store.alerts("open")) == 1
    s.core.status = "unavailable"
    assert s.operational()["status"] == "unavailable"
    s.collect()
    assert len(s.store.alerts("open")) == 1  # missing data is not a recovery


def test_simulated_and_real_are_never_mixed_silently(tmp_path):
    s = svc(
        tmp_path,
        FakeCore(
            stations=[station(sim=False)],
            events=[inference(1, 0.1, sim=True), inference(2, 0.9, sim=False)],
        ),
    )
    assert s.operational(data_kind="real")["total"]["n_inferences"] == 1
    assert s.operational(data_kind="simulated")["total"]["n_inferences"] == 1
    assert s.operational()["total"]["simulated"] == [False, True]


def test_inference_is_never_linked_to_the_registry_by_name(tmp_path):
    s = svc(tmp_path, FakeCore([inference(1, 0.1)]))
    g = s.operational()["groups"][0]
    assert g["model_key"] == KEY and g["registry_link"] == "not associated with the registry"


def test_model_change_within_a_window_gives_separate_groups(tmp_path):
    events = [inference(i, 0.1, version="1") for i in range(5)] + [
        inference(i, 0.8, version="2") for i in range(5, 8)
    ]
    groups = svc(tmp_path, FakeCore(events)).operational()["groups"]
    assert {(g["model_version"], g["n_inferences"]) for g in groups} == {("1", 5), ("2", 3)}


def test_aggregate_rates_latency_and_window():
    infs, _, _ = observations(
        CoreSnapshot(
            [station()],
            [inference(i, 0.1 * i, latency=10 * (i + 1)) for i in range(10)],
            [],
            [],
            SourceStatus("core", "available"),
        )
    )
    a = aggregate(infs, T0, T0 + timedelta(hours=2))
    assert a["n_inferences"] == 10 and a["cadence_per_hour"] == 5
    assert sum(a["decision_counts"].values()) == 10 and a["latency_ms"]["p50"] == pytest.approx(55)
    assert sum(a["score_histogram"]["counts"]) == 10


def test_parts_errors_come_from_the_parts_api_only(tmp_path):
    s = svc(
        tmp_path,
        FakeCore(parts=[part("p1", "OK"), part("p2", None, error={"code": "MODEL_TIMEOUT"})]),
    )
    assert s.operational()["parts"]["error_codes"] == {"MODEL_TIMEOUT": 1}


# --------------------------------------------------------------------------- human


def test_successive_corrections_keep_the_initial_ai_verdict_and_the_last_human_one():
    parts = [part("p1", "NOK"), part("p2", "OK"), part("p3", "OK")]
    snap = CoreSnapshot(
        [station()],
        [correction("p1", 1, "NOK"), correction("p1", 2, "OK"), correction("p2", 1, "NOK")],
        parts,
        [],
        SourceStatus("core", "available"),
    )
    _, ps, cs = observations(snap)
    h = human(ps, cs)
    assert h["corrected_parts"] == 2 and h["corrections"] == 3
    assert h["false_rejects_observed"] == 1 and h["missed_defects_observed"] == 1
    assert h["correction_types"] == {"NOK->OK": 1, "OK->NOK": 1}


def test_no_agreement_rate_without_a_human_denominator():
    h = human([part("p1", "OK"), part("p2", "OK")], [])
    assert h["verified_parts"] is None and h["agreement_rate"] is None
    assert "unavailable" in h["agreement_status"]  # uncorrected parts are NOT confirmations


def test_duplicate_correction_events_are_counted_once():
    snap = CoreSnapshot(
        [station()],
        [
            correction("p1", 1, "OK", cid="c1"),
            {**correction("p1", 1, "OK", cid="c1"), "event_id": "x"},
        ],
        [part("p1", "NOK")],
        [],
        SourceStatus("core", "available"),
    )
    _, ps, cs = observations(snap)
    assert human(ps, cs)["corrections"] == 1


# --------------------------------------------------------------------------- references and drift


def test_reference_too_small_is_flagged_and_gives_no_alert(tmp_path):
    s = svc(tmp_path, FakeCore())
    ref = op_reference(s, n=40)
    assert ref["representative"] is False and ref["warnings"]
    infs = select(observations(s.core.snapshot())[0], key=KEY)
    assert (
        s.drift(ref, infs, KEY, "1", True, ref["score_definition"])["status"]
        == "insufficient_reference"
    )


def test_population_too_small(tmp_path):
    s = svc(tmp_path, FakeCore())
    ref = op_reference(s)
    pop = [inference(i, 0.9) for i in range(20)]
    infs = observations(CoreSnapshot([station()], pop, [], [], SourceStatus("core", "available")))[
        0
    ]
    assert (
        s.drift(ref, infs, KEY, "1", True, ref["score_definition"])["status"]
        == "insufficient_current"
    )


def test_incompatible_scores_and_synthetic_vs_real_are_refused(tmp_path):
    s = svc(tmp_path, FakeCore())
    ref = op_reference(s, sim=True)
    pop = select(observations(s.core.snapshot())[0], key=KEY)
    other = s.drift(ref, pop, KEY, "1", True, "another score")
    assert (
        other["status"] == "incompatible" and "incompatible score definitions" in other["reasons"]
    )
    real = s.drift(ref, pop, KEY, "1", False, ref["score_definition"])
    assert real["status"] == "incompatible" and any("synthetic" in r for r in real["reasons"])
    assert s.drift(ref, pop, KEY, "2", True, ref["score_definition"])["status"] == "incompatible"


def test_drift_measures_on_a_shifted_population(tmp_path):
    s = svc(tmp_path, FakeCore())
    ref = op_reference(s, n=300, mu=0.2)
    pop = [
        inference(i, x, latency=40.0, at=T0 + timedelta(days=1, seconds=i))
        for i, x in enumerate(scores(300, 0.6, seed=5))
    ]
    infs = observations(CoreSnapshot([station()], pop, [], [], SourceStatus("core", "available")))[
        0
    ]
    out = s.drift(ref, infs, KEY, "1", True, ref["score_definition"])
    by = {(m["indicator"], m["method"]): m for m in out["measures"]}
    assert out["status"] == "available"
    assert by[("score", "psi")]["level"] == "alert" and by[("score", "ks")]["p_value"] < 1e-6
    assert by[("latency", "mean_shift")]["level"] == "alert"
    assert "not a proof of concept drift" in out["note"]


def test_references_are_immutable_and_refuse_mixed_data(tmp_path):
    s = svc(tmp_path, FakeCore())
    op_reference(s)
    with pytest.raises(ValueError, match="immutable"):
        s.operational_reference(KEY, "1", T0, T0 + timedelta(hours=1), "simulated")
    with pytest.raises(ValueError):
        s.operational_reference(KEY, "1", T0, T0 + timedelta(hours=1), "all")


def test_offline_reference_of_an_18_image_test_is_not_representative(tmp_path):
    csv_rows = "fichier,verdict,score_nok,latence_ms\n" + "".join(
        f"img{i}.jpg,{'NOK' if i % 3 else 'OK'},0.{i % 9},12\n" for i in range(18)
    )
    run = SimpleNamespace(tags={"argos.dataset_id": "quality-synthetic-3c"}, params={}, metrics={})
    version = SimpleNamespace(version=SimpleNamespace(version="1", run_id="r1"))
    conn = SimpleNamespace(
        model_status=lambda m: SimpleNamespace(versions=[version]), get_run=lambda r: run
    )
    training = SimpleNamespace(_artifact=lambda r, p: csv_rows.encode())
    s = MonitoringService(
        conn, FakeCore(), MonitoringStore(tmp_path / "m.sqlite"), training=training
    )
    ref = s.offline_reference("quality-industrial", "1")
    assert ref["n"] == 18 and ref["representative"] is False and ref["synthetic"] is True
    assert ref["decision_counts"] == {"conforme": 6, "anomalie": 12}
    assert ref["edges"][0] is None and ref["edges"][-1] is None  # open edges stored as JSON null


# ------------------------------------------------------------- collection, history, alerts


def test_collection_is_idempotent_and_reconciles_late_events(tmp_path):
    core = FakeCore([inference(i, 0.1) for i in range(5)])
    s = svc(tmp_path, core)
    s.collect()
    s.collect()
    snaps = s.store.snapshots()
    assert len(snaps) == 1 and snaps[0]["n_inferences"] == 5
    core.events.append(inference(99, 0.2, at=T0 + timedelta(hours=3)))  # late event, same day
    s.collect()
    snaps = s.store.snapshots()
    assert len(snaps) == 1 and snaps[0]["n_inferences"] == 6


def test_history_persists_after_reopening_the_store(tmp_path):
    s = svc(tmp_path, FakeCore([inference(1, 0.1)]))
    s.collect()
    op_reference(s, n=10, day=2)
    reopened = MonitoringStore(tmp_path / "m.sqlite")
    assert (
        len(reopened.snapshots()) == 1
        and len(reopened.references()) == 1
        and len(reopened.collections()) == 1
    )


def test_persistent_drift_keeps_a_single_alert_and_resolves(tmp_path):
    s = svc(tmp_path, FakeCore())
    op_reference(s, n=300, mu=0.2)  # day 0 = reference window
    day1 = [
        inference(1000 + i, x, at=T0 + timedelta(days=1, seconds=i))
        for i, x in enumerate(scores(300, 0.7, seed=9))
    ]
    s.core.events += day1  # latest day strongly shifted
    s.collect()
    first = [a for a in s.store.alerts("open") if a["kind"] == "drift"]
    s.collect()
    again = [a for a in s.store.alerts("open") if a["kind"] == "drift"]
    assert first and len(again) == len(first)  # persistent drift: no duplicate
    assert [a["first_detected"] for a in again] == [a["first_detected"] for a in first]
    s.core.events = [e for e in s.core.events if e not in day1]  # latest day = reference again
    s.collect()
    assert not [a for a in s.store.alerts("open") if a["kind"] == "drift"]
    assert len([a for a in s.store.alerts("resolved") if a["kind"] == "drift"]) == len(first)


def test_get_requests_never_write_and_never_call_a_warehouse(tmp_path):
    s = svc(tmp_path, FakeCore([inference(1, 0.1)], stations=[station(runtime="down")]))
    calls = []

    class Conn:
        settings = SimpleNamespace(request_budget_seconds=30, models=[])

        def _cached(self, key, loader, ttl=None):
            return loader()

        def __getattr__(self, name):  # any warehouse / SQL / remote call would land here
            calls.append(name)
            raise AssertionError(f"unexpected remote call {name}")

    from mlops.api.monitoring_routes import create_monitoring_router

    conn = Conn()
    s.c = conn
    app = FastAPI()
    app.include_router(
        create_monitoring_router(lambda: conn, get_service=lambda c: s), prefix="/api"
    )
    client = TestClient(app)
    for url in [
        "summary",
        "models",
        f"models/{KEY}",
        "inferences?data_kind=simulated",
        "human",
        "alerts",
        "history",
        "references",
        f"drift?model_key={KEY}&version=1&data_kind=simulated",
    ]:
        r = client.get(f"/api/mlops/monitoring/{url}")
        assert r.status_code == 200, (url, r.text)
    assert (
        client.get(f"/api/mlops/monitoring/drift?model_key={KEY}&version=1").json()["status"]
        == "reference_absent"
    )
    assert (
        s.store.snapshots() == []
        and s.store.alerts() == []
        and s.store.collections() == []
        and s.store.references() == []
    )
    assert calls == []
    r = client.post("/api/mlops/monitoring/collect")
    assert r.status_code == 200 and len(s.store.alerts("open")) == 1
    body = {
        "source": "operational_window",
        "model_key": KEY,
        "version": "1",
        "start": T0.isoformat(),
        "end": (T0 + timedelta(hours=1)).isoformat(),
        "data_kind": "simulated",
    }
    r = client.post("/api/mlops/monitoring/references", json=body)
    assert r.status_code == 201 and r.json()["representative"] is False
    assert (
        client.post("/api/mlops/monitoring/references", json=body).status_code == 409
    )  # immutable


def test_offline_performance_of_a_tiny_test_is_flagged_not_representative():
    from mlops.monitoring.service import _representativeness

    assert _representativeness(18, 100)["representative"] is False
    assert _representativeness(None, 100)["representative"] is None
    assert _representativeness(400, 100)["representative"] is True
