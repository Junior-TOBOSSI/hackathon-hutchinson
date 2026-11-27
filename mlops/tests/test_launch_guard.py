"""DBX-08A security: ONE launch path for trainings (TrainingService.launch), every remote job
behind HOVIS_TRAINING_REMOTE, every attempt journaled. No Databricks call is made."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.api import routes
from mlops.databricks.connector import ForbiddenOperationError
from mlops.databricks.training import DatabricksJobBackend
from mlops.tests.test_databricks_unit import connector  # noqa: F401 - shared fixture
from mlops.training import service as svc


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "HOME", tmp_path)
    monkeypatch.delenv("HOVIS_TRAINING_REMOTE", raising=False)


def test_training_jobs_are_never_triggered_directly_even_when_authorized(connector, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HOVIS_TRAINING_REMOTE", "1")
    with pytest.raises(ForbiddenOperationError, match="training/launch"):
        connector.trigger_job("train-q")
    connector.w.jobs.run_now.assert_not_called()


def test_other_jobs_need_the_lock_then_the_allow_list(connector, monkeypatch):  # noqa: F811
    with pytest.raises(ForbiddenOperationError, match="HOVIS_TRAINING_REMOTE"):
        connector.trigger_job("extra-job")
    monkeypatch.setenv("HOVIS_TRAINING_REMOTE", "1")
    with pytest.raises(ForbiddenOperationError, match="not triggerable"):
        connector.trigger_job("extra-job")
    connector.w.jobs.run_now.assert_not_called()


def test_legacy_backend_submit_is_disabled(connector):  # noqa: F811
    with pytest.raises(ForbiddenOperationError, match="TrainingService.launch"):
        DatabricksJobBackend(connector).submit("q")
    connector.w.jobs.run_now.assert_not_called()


def test_lock_is_checked_before_any_validation_and_journaled(tmp_path):
    c = MagicMock()
    s = svc.TrainingService(c, specs=[], launches=svc.LaunchStore(tmp_path / "l.json"))
    s.validate = MagicMock()
    with pytest.raises(ForbiddenOperationError):
        s.launch("p", "d", "v1", {}, "k1", source="policy:x")
    s.validate.assert_not_called()
    c.w.jobs.run_now.assert_not_called()
    last = s.audit.tail(1)[0]
    assert last["outcome"] == "refused_lock" and last["source"] == "policy:x"


@pytest.fixture
def api(connector):  # noqa: F811
    app = FastAPI()
    app.include_router(routes.create_mlops_router(lambda: connector), prefix="/api")
    return TestClient(app)


def test_every_launch_route_refuses_without_authorization(api, connector):  # noqa: F811
    assert api.get("/api/mlops/training/launch-guard").json()["remote_launch_enabled"] is False
    assert api.post("/api/models/q/retrain").status_code == 403
    body = {"dataset_id": "d", "version": "v1", "idempotency_key": "k"}
    assert api.post("/api/models/q/retrain", json=body).status_code == 403
    assert api.post("/api/mlops/jobs/train-q/run").status_code == 403
    assert api.post("/api/mlops/jobs/extra-job/run").status_code == 403
    launch = {"pipeline_id": "p", "dataset_id": "d", "version": "v1", "idempotency_key": "k"}
    assert api.post("/api/mlops/training/launch", json=launch).status_code == 403
    assert api.post("/api/mlops/training/runs/1/cancel").status_code == 403
    connector.w.jobs.run_now.assert_not_called()
    connector.w.jobs.cancel_run.assert_not_called()
    outcomes = [e["outcome"] for e in api.get("/api/mlops/training/launch-audit").json()]
    assert outcomes.count("refused_lock") >= 4


def test_legacy_route_is_connected_to_the_single_launch_path(api, connector, monkeypatch):  # noqa: F811
    monkeypatch.setenv("HOVIS_TRAINING_REMOTE", "1")
    assert api.post("/api/models/q/retrain").status_code == 422  # no implicit dataset choice
    from mlops.api.training_routes import service_for

    s = service_for(connector)
    calls = []
    monkeypatch.setattr(s, "pipeline_for_model", lambda m: SimpleNamespace(id="pipe-q"))
    monkeypatch.setattr(
        s,
        "launch",
        lambda *a, **k: (
            calls.append((a, k))
            or svc.LaunchRecord(
                request_id="r",
                idempotency_key="k",
                pipeline_id="pipe-q",
                dataset_id="d",
                dataset_version="v1",
                parameters={},
                status="submitted",
                job_run_id=5,
                created_at="t",
            )
        ),
    )
    r = api.post(
        "/api/models/q/retrain", json={"dataset_id": "d", "version": "v1", "idempotency_key": "k"}
    )
    assert r.status_code == 202 and r.json()["job_run_id"] == 5
    assert calls == [(("pipe-q", "d", "v1", {}, "k"), {"source": "legacy:/models/retrain"})]
    connector.w.jobs.run_now.assert_not_called()
