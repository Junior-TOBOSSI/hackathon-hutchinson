"""CORE-02: real Production Engine facts cross the contracted HTTP inbox."""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from visionhub.argos_app import create_argos_app
from visionhub.config import Settings
from visionhub.core.app import create_app as create_core_app
from visionhub.integration.edge_events import IngestAck, IngestResult
from visionhub.production.sync import OutboxSender, validate_core_url


def edge_app(path: str):
    settings = Settings(_env_file=None, db_path=path, pipeline_enabled=False, source="synthetic")
    return create_argos_app(settings, core_url="")


def cycle(edge: TestClient, cycle_id: str = "C-1") -> dict:
    response = edge.post(
        "/production/stations/WS-01/cycles",
        data={"cycle_id": cycle_id, "simulated": "true"},
    )
    assert response.status_code == 201
    return response.json()


def bridge(core: TestClient):
    def forward(request: httpx.Request) -> httpx.Response:
        response = core.post(
            request.url.path, content=request.content, headers={"content-type": "application/json"}
        )
        return httpx.Response(response.status_code, json=response.json())

    return httpx.MockTransport(forward)


def drain(sender: OutboxSender) -> None:
    for _ in range(20):
        if sender.send_once() is None:
            return
    raise AssertionError("outbox did not drain")


def test_production_engine_to_core_cycle_correction_disposition_and_shifts(tmp_path):
    with TestClient(create_core_app(str(tmp_path / "core.sqlite3"))) as core:
        with TestClient(edge_app(str(tmp_path / "edge.sqlite3"))) as edge:
            assert edge.put("/thresholds/quality", json={"low": 0, "high": 0}).status_code == 200
            shift = edge.post(
                "/production/stations/WS-01/shifts", json={"name": "demo", "target_parts": 8}
            ).json()
            part = cycle(edge)
            assert part["predicted_verdict"] == "NOK"
            assert (
                edge.post(
                    "/production/parts/{}/corrections".format(part["part_id"]),
                    json={
                        "new_verdict": "OK",
                        "expected_current_verdict": "NOK",
                        "reason": "Synthetic physical check",
                        "actor_role": "operator",
                    },
                ).status_code
                == 201
            )
            assert (
                edge.put(
                    f"/production/parts/{part['part_id']}/disposition",
                    json={"disposition": "QUARANTINED"},
                ).status_code
                == 200
            )
            assert edge.post(f"/production/shifts/{shift['shift_id']}/close").status_code == 200

            local = edge.get("/edge/sync/status").json()
            assert local["configured"] is False
            assert local["pending"] == 6  # open, inference, part, correction, disposition, close
            assert core.get("/health").json()["parts"] == 0
            sender = OutboxSender(
                edge.app.state.production.store, "http://127.0.0.1:8020", transport=bridge(core)
            )
            drain(sender)
            assert edge.get("/edge/sync/status").json()["delivered"] == 6
            assert core.get("/health").json()["events"] == 6
            core_part = core.get("/api/v1/parts", params={"station_id": "WS-01"}).json()[0]
            assert core_part["part_id"] == part["part_id"]
            assert core_part["predicted_verdict"] == "NOK"
            assert core_part["effective_verdict"] == "OK"
            assert core_part["disposition"] == "QUARANTINED"
            assert core.get("/api/v1/kpi").json()["ok_parts"] == 1
            assert core.get("/api/v1/stations/WS-01").json()["current_shift"] is None
            assert core.get("/api/v1/alerts").json()
            assert cycle_replay(edge, "C-1") == part["part_id"]
            assert edge.get("/edge/sync/status").json()["total"] == 6


def cycle_replay(edge: TestClient, cycle_id: str) -> str:
    response = edge.post(
        "/production/stations/WS-01/cycles",
        data={"cycle_id": cycle_id, "simulated": "true"},
    )
    assert response.status_code == 200
    assert response.headers["Idempotent-Replay"] == "true"
    return response.json()["part_id"]


def test_lost_ack_and_edge_restart_replay_without_duplicate_part(tmp_path):
    edge_path = str(tmp_path / "edge.sqlite3")
    with TestClient(create_core_app(str(tmp_path / "core.sqlite3"))) as core:
        with TestClient(edge_app(edge_path)) as edge:
            part = cycle(edge)
            calls = 0

            def lost_ack(request: httpx.Request) -> httpx.Response:
                nonlocal calls
                calls += 1
                response = core.post(
                    request.url.path,
                    content=request.content,
                    headers={"content-type": "application/json"},
                )
                assert response.status_code == 200
                raise httpx.ReadTimeout("synthetic lost ACK")

            sender = OutboxSender(
                edge.app.state.production.store,
                "http://127.0.0.1:8020",
                transport=httpx.MockTransport(lost_ack),
            )
            assert sender.send_once() is False
            assert calls == 1
            assert edge.get("/edge/sync/status").json()["pending"] == 2
            assert core.get("/health").json()["parts"] == 1
        with TestClient(edge_app(edge_path)) as restarted:
            sender = OutboxSender(
                restarted.app.state.production.store,
                "http://127.0.0.1:8020",
                transport=bridge(core),
            )
            drain(sender)
            assert restarted.get("/edge/sync/status").json()["pending"] == 0
            assert restarted.get("/edge/sync/status").json()["delivered"] == 2
            assert cycle_replay(restarted, "C-1") == part["part_id"]
            assert core.get("/health").json()["parts"] == 1
            assert core.get("/health").json()["events"] == 2


def test_core_unavailable_retains_correction_until_recovery(tmp_path):
    with TestClient(create_core_app(str(tmp_path / "core.sqlite3"))) as core:
        with TestClient(edge_app(str(tmp_path / "edge.sqlite3"))) as edge:
            edge.put("/thresholds/quality", json={"low": 0, "high": 0})
            part = cycle(edge)

            def disconnected(_request: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("synthetic Core outage")

            sender = OutboxSender(
                edge.app.state.production.store,
                "http://127.0.0.1:8020",
                transport=httpx.MockTransport(disconnected),
            )
            assert sender.send_once() is False
            assert (
                edge.post(
                    f"/production/parts/{part['part_id']}/corrections",
                    json={
                        "new_verdict": "OK",
                        "expected_current_verdict": "NOK",
                        "reason": "Inspected during outage",
                        "actor_role": "operator",
                    },
                ).status_code
                == 201
            )
            assert edge.get("/edge/sync/status").json()["pending"] == 3
            assert core.get("/health").json()["parts"] == 0
            drain(
                OutboxSender(
                    edge.app.state.production.store, "http://127.0.0.1:8020", transport=bridge(core)
                )
            )
            assert edge.get("/edge/sync/status").json()["pending"] == 0
            received = core.get("/api/v1/parts").json()[0]
            assert received["effective_verdict"] == "OK"
            assert received["correction_count"] == 1


def test_rejected_ack_remains_in_outbox(tmp_path):
    with TestClient(edge_app(str(tmp_path / "edge.sqlite3"))) as edge:
        cycle(edge)
        store = edge.app.state.production.store
        events = store.pending_events()
        ack = IngestAck(
            station_id="WS-01",
            received_at=events[0].occurred_at,
            results=[
                IngestResult(event_id=e.event_id, status="rejected", error="synthetic conflict")
                for e in events
            ],
            highest_contiguous_sequence=0,
        )
        store.mark_ack(ack, events)
        assert store.outbox_status()["rejected"] == 2
        assert store.outbox_status()["delivered"] == 0
        assert store.pending_events() == []
        with sqlite3.connect(tmp_path / "edge.sqlite3") as conn:
            assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 2


def test_outbox_write_failure_rolls_back_part_and_event(tmp_path, monkeypatch):
    import visionhub.production.store as production_store

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("synthetic outbox disk failure")

    monkeypatch.setattr(production_store, "enqueue", fail)
    settings = Settings(
        _env_file=None, db_path=str(tmp_path / "edge.sqlite3"), pipeline_enabled=False
    )
    with TestClient(create_argos_app(settings, core_url="")) as edge:
        with pytest.raises(sqlite3.OperationalError):
            edge.post(
                "/production/stations/WS-01/cycles",
                data={"cycle_id": "C-1", "simulated": "true"},
            )
        assert edge.app.state.production.store.get_part_by_cycle("WS-01", "C-1") is None
        assert edge.get("/edge/sync/status").json()["total"] == 0
        assert edge.get("/events").json() == []


def test_external_core_destination_is_refused():
    with pytest.raises(ValueError):
        validate_core_url("https://example.com")
