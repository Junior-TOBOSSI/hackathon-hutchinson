import time

import cv2
import pytest
from fastapi.testclient import TestClient

from visionhub.argos_app import create_argos_app
from visionhub.config import Settings
from visionhub.sources import synthetic_frame

P = "/production"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "argos.db")


@pytest.fixture
def open_client(db_path, clock):
    def factory(**overrides):
        settings = Settings(_env_file=None, db_path=db_path, pipeline_enabled=False, **overrides)
        return TestClient(create_argos_app(settings, clock=clock))

    return factory


@pytest.fixture
def client(open_client):
    with open_client() as c:
        yield c


def cycle(client, cycle_id, station="WS-01", image=None, **form):
    data = {"cycle_id": cycle_id, "simulated": "true", **form}
    files = {"image": ("part.png", image, "image/png")} if image is not None else None
    return client.post(f"{P}/stations/{station}/cycles", data=data, files=files)


def png(index=0) -> bytes:
    return cv2.imencode(".png", synthetic_frame(index))[1].tobytes()


def thresholds(client, low, high):
    assert client.put("/thresholds/quality", json={"low": low, "high": high}).status_code == 200


def correct(client, part, new, reason="vérifié sur la pièce", **extra):
    body = {
        "new_verdict": new,
        "expected_current_verdict": part["effective_verdict"],
        "reason": reason,
        "actor_role": "operator",
        **extra,
    }
    return client.post(f"{P}/parts/{part['part_id']}/corrections", json=body)


def test_acceptance_scenario(open_client, clock):
    # 1-2. Start ARGOS, open a shift with a target.
    with open_client() as client:
        r = client.post(f"{P}/stations/WS-01/shifts", json={"name": "matin", "target_parts": 20})
        assert r.status_code == 201
        shift = r.json()
        assert shift["status"] == "OPEN" and shift["planned_end_at"]

        # 3-4. Simulated PLC cycles: 3 OK, 2 NOK, 1 HOLD, 1 ERROR.
        plan = [(1, 1, "OK")] * 3 + [(0, 0, "NOK")] * 2 + [(0, 1, "HOLD")]
        parts = []
        for i, (low, high, expected) in enumerate(plan):
            thresholds(client, low, high)
            clock.advance(minutes=5)
            r = cycle(client, f"SIM-T-{i:06d}")
            assert r.status_code == 201, r.text
            assert r.json()["predicted_verdict"] == expected
            parts.append(r.json())
        error = cycle(client, "REAL-000001", simulated="false").json()  # no image: ERROR
        assert error["error"]["code"] == "CAPTURE_FAILED"

        # 5. Counters.
        kpi = client.get(f"{P}/stations/WS-01/shifts/current").json()["kpi"]
        counts = [kpi[k] for k in ("total_parts", "ok_parts", "nok_parts", "hold_parts")]
        assert counts == [7, 3, 2, 1] and kpi["error_parts"] == 1
        assert kpi["target_progress"] == 3 / 20

        # 6. A duplicated cycle changes nothing.
        r = cycle(client, "SIM-T-000000")
        assert r.status_code == 200 and r.headers["Idempotent-Replay"] == "true"
        assert r.json() == parts[0]
        assert client.get(f"{P}/stations/WS-01/shifts/current").json()["kpi"] == kpi

        # 7-9. NOK -> OK; KPIs updated; original prediction unchanged.
        nok = parts[3]
        r = correct(client, nok, "OK", reason="pièce vérifiée conforme, faux rejet")
        assert r.status_code == 201
        corrected = r.json()
        assert corrected["effective_verdict"] == "OK"
        assert corrected["predicted_verdict"] == "NOK"
        assert corrected["prediction"] == nok["prediction"]
        kpi2 = client.get(f"{P}/stations/WS-01/shifts/current").json()["kpi"]
        assert (kpi2["ok_parts"], kpi2["nok_parts"], kpi2["corrected_parts"]) == (4, 1, 1)
        assert kpi2["predicted_nok_parts"] == 2

        # 10. Correction history.
        history = client.get(f"{P}/parts/{nok['part_id']}/corrections").json()
        assert [(h["previous_verdict"], h["new_verdict"]) for h in history] == [("NOK", "OK")]
        assert history[0]["actor_role"] == "operator" and "actor_ref" not in history[0]

    # 11-12. Restart: parts, shifts and corrections persist; idempotence too.
    with open_client() as client:
        report = client.get(f"{P}/shifts/{shift['shift_id']}").json()
        assert report["kpi"]["ok_parts"] == 4 and report["kpi"]["total_parts"] == 7
        assert client.get(f"{P}/parts/{nok['part_id']}").json() == corrected
        assert len(client.get(f"{P}/parts/{nok['part_id']}/corrections").json()) == 1
        assert cycle(client, "SIM-T-000001").status_code == 200
        assert len(client.get(f"{P}/parts", params={"limit": 100}).json()) == 7


def test_cycle_http_codes(client):
    assert cycle(client, "C1", image=png(0)).status_code == 201
    assert cycle(client, "C1", image=png(0)).status_code == 200
    r = cycle(client, "C1", image=png(1))
    assert r.status_code == 409 and "already recorded" in r.json()["detail"]
    assert cycle(client, "bad id with spaces").status_code == 422
    assert cycle(client, "C2", station="bad-station!").status_code == 422
    assert client.post(f"{P}/stations/WS-01/cycles", data={}).status_code == 422
    r = cycle(client, "C3", image=b"garbage", simulated="false")
    assert r.status_code == 201 and r.json()["error"]["code"] == "IMAGE_DECODE_FAILED"


def test_part_lookups_and_404(client):
    part = cycle(client, "C1").json()
    assert client.get(f"{P}/stations/WS-01/cycles/C1").json() == part
    assert client.get(f"{P}/parts/{part['part_id']}").json() == part
    assert client.get(f"{P}/parts", params={"verdict": part["effective_verdict"]}).json()
    assert client.get(f"{P}/parts", params={"station_id": "WS-99"}).json() == []
    for path in (
        f"{P}/parts/nope",
        f"{P}/parts/nope/corrections",
        f"{P}/stations/WS-01/cycles/nope",
        f"{P}/shifts/nope",
        f"{P}/stations/WS-01/shifts/current",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post(f"{P}/shifts/nope/close").status_code == 404


def test_correction_http_codes(client):
    thresholds(client, 0, 0)
    part = cycle(client, "C1").json()
    stale = {**part, "effective_verdict": "OK"}
    assert correct(client, stale, "NOK").status_code == 409
    assert correct(client, part, "NOK").status_code == 422  # already NOK
    assert correct(client, part, "HOLD").status_code == 422
    assert correct(client, part, "OK", reason="").status_code == 422
    assert correct(client, part, "OK", badge_id="42").status_code == 422
    assert correct(client, part, "OK").status_code == 201

    thresholds(client, 0, 1)
    hold = cycle(client, "C2").json()
    assert correct(client, hold, "OK").status_code == 422  # physical inspection required
    assert correct(client, hold, "OK", physical_inspection=True).status_code == 201


def test_shift_http_codes(client, clock):
    body = {"name": "matin", "target_parts": 10}
    shift = client.post(f"{P}/stations/WS-01/shifts", json=body).json()
    assert client.post(f"{P}/stations/WS-01/shifts", json=body).status_code == 409
    assert client.post(f"{P}/stations/WS-01/shifts", json={"name": "x"}).status_code == 422
    clock.advance(hours=1)
    r = client.post(f"{P}/shifts/{shift['shift_id']}/close")
    assert r.status_code == 200 and r.json()["shift"]["status"] == "CLOSED"
    assert client.post(f"{P}/shifts/{shift['shift_id']}/close").status_code == 409
    assert [s["shift_id"] for s in client.get(f"{P}/shifts").json()] == [shift["shift_id"]]


def test_disposition_is_not_a_verdict(client):
    part = cycle(client, "C1").json()
    r = client.put(f"{P}/parts/{part['part_id']}/disposition", json={"disposition": "SCRAPPED"})
    assert r.status_code == 200
    assert r.json()["disposition"] == "SCRAPPED"
    assert r.json()["effective_verdict"] == part["effective_verdict"]
    bad = client.put(f"{P}/parts/{part['part_id']}/disposition", json={"disposition": "GONE"})
    assert bad.status_code == 422


def test_station_kpi_endpoint(client, clock):
    start = clock().isoformat()
    cycle(client, "C1")
    clock.advance(minutes=1)
    r = client.get(f"{P}/stations/WS-01/kpi", params={"from": start})
    assert r.status_code == 200 and r.json()["total_parts"] == 1
    assert client.get(f"{P}/stations/WS-01/kpi").json()["total_parts"] == 1  # default window
    r = client.get(f"{P}/stations/WS-01/kpi", params={"from": "2030-01-01T00:00:00", "to": start})
    assert r.status_code == 422


def test_historical_api_is_unchanged_and_sees_cycle_events(client):
    assert client.get("/health").json()["status"] == "ok"
    assert {u["use_case"] for u in client.get("/use-cases").json()} == {
        "quality",
        "workstation",
        "safety",
    }
    thresholds(client, 0, 1)  # HOLD
    part = cycle(client, "C1").json()
    events = client.get("/events").json()
    assert [e["frame"]["frame_id"] for e in events] == ["cycle:WS-01:C1"]
    # The historical feedback endpoint is NOT a source of truth for parts.
    event_id = part["prediction"]["event_id"]
    assert client.post(f"/events/{event_id}/feedback", json={"verdict": "conforme"}).is_success
    assert client.get(f"{P}/parts/{part['part_id']}").json()["effective_verdict"] == "HOLD"


def test_background_inference_does_not_count_as_production(open_client, db_path):
    settings = Settings(_env_file=None, db_path=db_path, pipeline_enabled=True, pipeline_fps=50)
    with TestClient(create_argos_app(settings)) as client:
        deadline = time.time() + 10
        while client.get("/stats").json()["total"] < 9 and time.time() < deadline:
            time.sleep(0.1)
        assert client.get("/stats").json()["total"] >= 9
        assert client.get(f"{P}/stations/WS-01/kpi").json()["total_parts"] == 0
        assert client.get(f"{P}/parts").json() == []
