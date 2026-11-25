import time

import cv2
import pytest
from fastapi.testclient import TestClient

from visionhub.api import create_app
from visionhub.config import Settings
from visionhub.sources import synthetic_frame


def client_for(**overrides) -> TestClient:
    settings = Settings(_env_file=None, db_path=":memory:", **overrides)
    return TestClient(create_app(settings))


@pytest.fixture
def client():
    # Pipeline disabled: the tests control exactly which events exist.
    with client_for(pipeline_enabled=False) as c:
        yield c


def png_bytes() -> bytes:
    ok, buf = cv2.imencode(".png", synthetic_frame(0))
    assert ok
    return buf.tobytes()


def analyze(client, **params):
    files = {"image": ("frame.png", png_bytes(), "image/png")}
    return client.post("/analyze", files=files, params=params)


def test_health_and_use_cases(client):
    assert client.get("/health").json()["status"] == "ok"
    infos = client.get("/use-cases").json()
    assert {i["use_case"] for i in infos} == {"quality", "workstation", "safety"}
    assert all(i["status"] == "ok" and i["version"] for i in infos)


def test_analyze_all_and_one(client):
    r = analyze(client)
    assert r.status_code == 200
    assert {e["use_case"] for e in r.json()} == {"quality", "workstation", "safety"}
    assert client.get("/events").json() == []  # store=false by default

    r = analyze(client, use_case="safety", store=True)
    assert [e["use_case"] for e in r.json()] == ["safety"]
    assert len(client.get("/events").json()) == 1


def test_analyze_rejects_non_image(client):
    files = {"image": ("x.png", b"not an image", "image/png")}
    assert client.post("/analyze", files=files).status_code == 400


def test_thresholds_change_next_decisions(client):
    r = client.put("/thresholds/quality", json={"low": 0.0, "high": 0.0})
    assert r.status_code == 200 and r.json()["thresholds"] == {"low": 0.0, "high": 0.0}
    assert analyze(client, use_case="quality").json()[0]["decision"] == "anomalie"

    client.put("/thresholds/quality", json={"low": 1.0, "high": 1.0})
    assert analyze(client, use_case="quality").json()[0]["decision"] == "conforme"

    client.put("/thresholds/quality", json={"low": 0.0, "high": 1.0})
    event = analyze(client, use_case="quality").json()[0]
    assert event["decision"] == "a_verifier"
    assert event["thresholds_used"] == {"low": 0.0, "high": 1.0}


def test_thresholds_validation(client):
    assert client.put("/thresholds/quality", json={"low": 0.9, "high": 0.1}).status_code == 422
    assert client.put("/thresholds/nope", json={"low": 0.1, "high": 0.9}).status_code == 422


def test_feedback_flow(client):
    client.put("/thresholds/safety", json={"low": 0.0, "high": 1.0})  # force a_verifier
    event = analyze(client, use_case="safety", store=True).json()[0]
    assert event["decision"] == "a_verifier"
    assert client.get("/stats").json()["pending_review"] == 1

    r = client.post(f"/events/{event['event_id']}/feedback", json={"verdict": "defaut"})
    assert r.status_code == 200 and r.json()["operator_feedback"]["verdict"] == "defaut"
    assert client.get("/stats").json()["pending_review"] == 0
    stored = client.get("/events", params={"decision": "a_verifier"}).json()[0]
    assert stored["operator_feedback"]["verdict"] == "defaut"

    assert client.post("/events/unknown/feedback", json={"verdict": "defaut"}).status_code == 404
    assert (
        client.post(f"/events/{event['event_id']}/feedback", json={"verdict": "x"}).status_code
        == 422
    )


def test_feedback_refused_on_non_review_event(client):
    client.put("/thresholds/quality", json={"low": 0.0, "high": 0.0})  # force anomalie
    event = analyze(client, use_case="quality", store=True).json()[0]
    r = client.post(f"/events/{event['event_id']}/feedback", json={"verdict": "conforme"})
    assert r.status_code == 409


def test_background_pipeline_fills_events_and_stats():
    with client_for(pipeline_enabled=True, pipeline_fps=50) as client:
        deadline = time.time() + 10
        while client.get("/stats").json()["total"] < 9 and time.time() < deadline:
            time.sleep(0.1)
        stats = client.get("/stats").json()
        assert stats["total"] >= 9
        assert set(stats["by_use_case"]) == {"quality", "workstation", "safety"}
        assert 0.0 <= stats["review_rate"] <= 1.0
        only_quality = client.get("/events", params={"use_case": "quality", "limit": 5}).json()
        assert only_quality and all(e["use_case"] == "quality" for e in only_quality)
