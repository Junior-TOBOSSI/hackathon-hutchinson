"""CORE-01 contract, durability and supervision tests using synthetic facts only."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from visionhub.core.app import create_app
from visionhub.core.simulator import make_events
from visionhub.integration.edge_events import EdgeEvent, EdgeEventBatch
from visionhub.production.contracts import Shift


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "core.sqlite3"))) as http:
        yield http


def send(client: TestClient, batch: EdgeEventBatch):
    return client.post("/ingest/v1/events", json=batch.model_dump(mode="json"))


def test_empty_core_has_no_invented_kpi(client):
    assert client.get("/health").json()["events"] == 0
    assert client.get("/api/v1/stations").json() == []
    kpi = client.get("/api/v1/kpi").json()
    assert kpi["total_parts"] == 0
    assert kpi["yield_rate"] is None
    assert kpi["actual_total_rate_per_hour"] == 0.0
    assert client.get("/api/v1/stations/WS-01").status_code == 404


def test_ingestion_ack_idempotence_and_conflicts(client):
    batch = make_events(stations=1, cycles=2)[0]
    first = send(client, batch)
    assert first.status_code == 200
    assert all(item["status"] == "accepted" for item in first.json()["results"])
    assert first.json()["highest_contiguous_sequence"] == len(batch.events)
    repeated = send(client, batch)
    assert all(item["status"] == "duplicate" for item in repeated.json()["results"])
    assert client.get("/health").json()["events"] == len(batch.events)
    assert client.get("/api/v1/kpi").json()["total_parts"] == 2

    original = batch.events[0]
    changed = original.model_copy(update={"simulated": False})
    conflict = EdgeEventBatch(station_id=batch.station_id, sent_at=batch.sent_at, events=[changed])
    answer = send(client, conflict).json()
    assert answer["results"][0]["status"] == "rejected"
    assert "different content" in answer["results"][0]["error"]
    different_id = original.model_copy(update={"event_id": "different-event-id"})
    sequence_conflict = EdgeEventBatch(
        station_id=batch.station_id, sent_at=batch.sent_at, events=[different_id]
    )
    assert send(client, sequence_conflict).json()["results"][0]["status"] == "rejected"
    part_event = next(e for e in batch.events if e.event_type.value == "part.recorded")
    second_part_id = part_event.model_copy(
        update={"event_id": "second-part-record", "edge_sequence": len(batch.events) + 1}
    )
    collision = EdgeEventBatch(
        station_id=batch.station_id, sent_at=batch.sent_at, events=[second_part_id]
    )
    assert send(client, collision).json()["results"][0]["status"] == "rejected"
    assert client.get("/health").json()["events"] == len(batch.events)


def test_invalid_batch_is_422_and_writes_nothing(client):
    batch = make_events(stations=1, cycles=1)[0].model_dump(mode="json")
    batch["events"][0]["payload"]["kind"] = "part.recorded"
    assert client.post("/ingest/v1/events", json=batch).status_code == 422
    assert client.get("/health").json()["events"] == 0


def test_out_of_order_correction_rebuilds_effective_verdict(client):
    batch = make_events(stations=2, cycles=2)[1]
    correction = next(e for e in batch.events if e.event_type.value == "part.corrected")
    later = [e for e in batch.events if e.edge_sequence >= correction.edge_sequence]
    earlier = [e for e in batch.events if e.edge_sequence < correction.edge_sequence]
    assert (
        send(
            client, EdgeEventBatch(station_id=batch.station_id, sent_at=batch.sent_at, events=later)
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/parts", params={"station_id": batch.station_id}).json()[0][
            "effective_verdict"
        ]
        == "NOK"
    )
    assert (
        send(
            client,
            EdgeEventBatch(station_id=batch.station_id, sent_at=batch.sent_at, events=earlier),
        ).status_code
        == 200
    )
    parts = client.get("/api/v1/parts", params={"station_id": batch.station_id}).json()
    corrected = next(p for p in parts if p["cycle_id"].endswith("-001"))
    assert corrected["predicted_verdict"] == "NOK"
    assert corrected["effective_verdict"] == "OK"
    assert corrected["correction_count"] == 1
    assert client.get("/api/v1/kpi").json()["corrected_parts"] == 1


def test_twelve_stations_weighted_kpi_and_inactive_station(client):
    batches = make_events(stations=12, cycles=4)
    for batch in batches:
        assert send(client, batch).status_code == 200
    stations = client.get("/api/v1/stations").json()
    assert len(stations) == 12
    assert all(station["simulated"] for station in stations)
    assert next(s for s in stations if s["station_id"] == "WS-01")["online"] is True
    assert sum(station["online"] for station in stations) == 11
    inactive = next(s for s in stations if s["station_id"] == "WS-12")
    assert inactive["online"] is False
    assert inactive["current_shift"]["kpi"]["total_parts"] == 0
    assert inactive["current_shift"]["kpi"]["yield_rate"] is None
    kpi = client.get("/api/v1/kpi").json()
    assert kpi["total_parts"] == 11 * 4
    assert (
        sum(kpi[key] for key in ("ok_parts", "nok_parts", "hold_parts", "error_parts"))
        == kpi["total_parts"]
    )
    assert kpi["yield_rate"] == pytest.approx(kpi["ok_parts"] / kpi["total_parts"])
    assert kpi["predicted_nok_parts"] > kpi["nok_parts"]
    assert kpi["error_parts"] >= 1
    assert kpi["mean_latency_ms"] is not None
    assert client.get("/api/v1/operator-reports").json()[0]["station_id"] == "WS-06"
    assert client.get("/api/v1/stations/WS-02/model-status").json()[0]["model_version"] == "1"


def test_kpi_window_boundaries_and_timezone_validation(client):
    base = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
    batch = make_events(stations=1, cycles=2, now=base)[0]
    send(client, batch)
    first_part = next(e.payload.part for e in batch.events if e.event_type.value == "part.recorded")
    start = first_part.created_at.isoformat()
    end = (first_part.created_at + timedelta(seconds=10)).isoformat()
    kpi = client.get("/api/v1/kpi", params={"from": start, "to": end}).json()
    assert kpi["total_parts"] == 1
    assert client.get("/api/v1/kpi", params={"from": end, "to": start}).status_code == 422
    assert client.get("/api/v1/kpi", params={"from": "2026-11-26T18:00:00"}).status_code == 422


def test_alert_episode_acknowledge_resolve_and_replay(client):
    batch = make_events(stations=3, cycles=2)[2]
    send(client, batch)
    alerts = client.get("/api/v1/alerts", params={"station_id": "WS-03"}).json()
    safety = [a for a in alerts if a["use_case"] == "safety"]
    assert len(safety) == 1
    assert safety[0]["occurrences"] == 3
    alert_id = safety[0]["alert_id"]
    assert client.post(f"/api/v1/alerts/{alert_id}/acknowledge").json()["status"] == "acknowledged"
    assert client.post(f"/api/v1/alerts/{alert_id}/resolve").json()["status"] == "resolved"
    assert client.post(f"/api/v1/alerts/{alert_id}/resolve").status_code == 409
    send(client, batch)
    assert (
        client.get("/api/v1/alerts", params={"station_id": "WS-03"}).json()[0]["occurrences"] == 3
    )
    assert client.get("/api/v1/alerts", params={"status": "resolved"}).status_code == 200

    source = next(e for e in batch.events if e.use_case == "safety")
    fresh = source.model_dump(mode="json")
    fresh["event_id"] = "fresh-safety-event"
    fresh["edge_sequence"] = max(e.edge_sequence for e in batch.events) + 1
    fresh["payload"]["event"]["event_id"] = "fresh-inference-event"
    later = EdgeEvent.model_validate(fresh)
    send(client, EdgeEventBatch(station_id="WS-03", sent_at=batch.sent_at, events=[later]))
    episodes = [
        a
        for a in client.get("/api/v1/alerts", params={"station_id": "WS-03"}).json()
        if a["use_case"] == "safety"
    ]
    assert len(episodes) == 2
    assert {a["status"] for a in episodes} == {"resolved", "open"}


def test_disposition_and_multiple_shifts_remain_distinct(client):
    batch = make_events(stations=2, cycles=2)[1]
    send(client, batch)
    parts = client.get("/api/v1/parts", params={"station_id": "WS-02"}).json()
    quarantined = next(p for p in parts if p["disposition"] == "QUARANTINED")
    assert quarantined["effective_verdict"] == "NOK"
    assert client.get("/api/v1/kpi").json()["nok_parts"] == 1

    opened = next(e for e in batch.events if e.event_type.value == "shift.opened")
    shift = opened.payload.shift
    closed_at = shift.started_at + timedelta(minutes=3)
    closed = Shift.model_validate({**shift.model_dump(), "status": "CLOSED", "ended_at": closed_at})
    close_event = EdgeEvent.model_validate(
        {
            **opened.model_dump(),
            "event_id": "close-shift-event",
            "event_type": "shift.closed",
            "edge_sequence": len(batch.events) + 1,
            "occurred_at": closed_at,
            "payload": {"kind": "shift", "shift": closed},
        }
    )
    send(client, EdgeEventBatch(station_id="WS-02", sent_at=batch.sent_at, events=[close_event]))
    assert client.get("/api/v1/stations/WS-02").json()["current_shift"] is None

    second = Shift(
        shift_id="second-shift",
        station_id="WS-02",
        name="second",
        status="OPEN",
        started_at=closed_at + timedelta(seconds=1),
        planned_duration_min=480,
        target_parts=0,
    )
    open_event = EdgeEvent.model_validate(
        {
            **opened.model_dump(),
            "event_id": "open-second-shift",
            "edge_sequence": len(batch.events) + 2,
            "occurred_at": second.started_at,
            "payload": {"kind": "shift", "shift": second},
        }
    )
    send(client, EdgeEventBatch(station_id="WS-02", sent_at=batch.sent_at, events=[open_event]))
    current = client.get("/api/v1/stations/WS-02").json()["current_shift"]
    assert current["shift"]["shift_id"] == "second-shift"
    assert current["kpi"]["total_parts"] == 0
    assert current["kpi"]["target_progress"] is None


def test_commit_failure_never_acknowledges_and_rolls_back(client, monkeypatch):
    batch = make_events(stations=1, cycles=1)[0]
    store = client.app.state.core
    original = store._rebuild_station

    def fail(*_args):
        raise sqlite3.OperationalError("injected disk error")

    monkeypatch.setattr(store, "_rebuild_station", fail)
    assert send(client, batch).status_code == 503
    assert client.get("/health").json()["events"] == 0
    monkeypatch.setattr(store, "_rebuild_station", original)
    assert all(r["status"] == "accepted" for r in send(client, batch).json()["results"])


def test_restart_keeps_inbox_alerts_and_rebuilds_projections(tmp_path):
    path = str(tmp_path / "persistent.sqlite3")
    batch = make_events(stations=2, cycles=2, now=datetime(2026, 11, 26, 18, 0, tzinfo=UTC))[1]
    bounds = {"from": "2026-11-26T17:00:00Z", "to": "2026-11-26T18:00:00Z"}
    with TestClient(create_app(path)) as first:
        send(first, batch)
        before = first.get("/api/v1/kpi", params=bounds).json()
        alerts = first.get("/api/v1/alerts").json()
    # Simulate a projection lost after a fault; the inbox remains the source of truth.
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM parts")
    with TestClient(create_app(path)) as second:
        assert second.get("/api/v1/kpi", params=bounds).json() == before
        assert len(second.get("/api/v1/alerts").json()) == len(alerts)
        assert all(r["status"] == "duplicate" for r in send(second, batch).json()["results"])
