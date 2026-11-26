"""Unit tests of the DBX-01 connector, API router and inference adapter (no Databricks)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.api import routes
from mlops.databricks.connector import (
    ConflictError,
    DatabricksConnector,
    ForbiddenOperationError,
    ResourceNotFoundError,
)
from mlops.databricks.inference import DatabricksQualityAnalyzer, EndpointClient, InferenceError
from mlops.databricks.settings import DatabricksSettings, ManagedModel
from visionhub.contracts import AnalysisResult, FrameMeta, QualityDetails

MODEL = ManagedModel(
    id="q",
    display_name="Q",
    use_case="Qualité",
    argos_use_case="quality",
    scope="test",
    uc_name="cat.sch.q",
    endpoint="ep",
    training_job="train-q",
)


def version(n, run="r1", tags=None):
    return SimpleNamespace(
        name="cat.sch.q",
        version=str(n),
        run_id=f"{run}{n}",
        model_id=None,
        source=f"models:/m-{n}",
        status="READY",
        tags=tags or {},
        creation_timestamp=1_700_000_000_000,
    )


def run(run_id, metrics=None, params=None):
    return SimpleNamespace(
        info=SimpleNamespace(
            run_id=run_id,
            run_name=run_id,
            experiment_id="1",
            status="FINISHED",
            start_time=1_700_000_000_000,
            end_time=None,
            artifact_uri="dbfs:/x",
        ),
        data=SimpleNamespace(params=params or {}, metrics=metrics or {}, tags={}),
    )


@pytest.fixture
def connector(monkeypatch):
    w, ml = MagicMock(), MagicMock()
    w.config.host = "https://example.cloud.databricks.com"
    ml.get_registered_model.return_value = SimpleNamespace(
        aliases={"champion": "2", "challenger": "1"}
    )
    ml.search_model_versions.return_value = [version(2), version(1)]
    ml.get_model_version.side_effect = lambda name, n: version(
        n, tags={"argos_approval": "approved"} if n == "2" else {}
    )
    ml.get_run.side_effect = lambda rid: run(
        rid, {"val_accuracy": 0.8, "test_recall_nok": 0.9}, {"dataset_version": "v1"}
    )
    endpoint = SimpleNamespace(
        name="ep",
        state=SimpleNamespace(
            ready=SimpleNamespace(value="READY"),
            config_update=SimpleNamespace(value="NOT_UPDATING"),
        ),
        config=SimpleNamespace(
            served_entities=[
                SimpleNamespace(
                    name="s",
                    entity_name="cat.sch.q",
                    entity_version="1",
                    workload_size="Small",
                    scale_to_zero_enabled=True,
                    state=None,
                )
            ]
        ),
        pending_config=None,
    )
    w.serving_endpoints.get.return_value = endpoint
    w.warehouses.list.return_value = [SimpleNamespace(id="wh")]
    w.warehouses.get.return_value = SimpleNamespace(state=SimpleNamespace(value="STOPPED"))
    settings = DatabricksSettings(models=(MODEL,), extra_triggerable_jobs=())
    for key in ("DATABRICKS_CONFIG_PROFILE", "MLFLOW_TRACKING_URI", "MLFLOW_REGISTRY_URI"):
        monkeypatch.setenv(key, "x")  # restored after the test
    return DatabricksConnector(settings, workspace=w, mlflow_client=ml)


# ------------------------------------------------------------------ settings


def test_settings_from_env(monkeypatch, tmp_path):
    models = tmp_path / "models.json"
    models.write_text(f"[{MODEL.model_dump_json()}]", encoding="utf-8")
    monkeypatch.setenv("ARGOS_DBX_MODELS_FILE", str(models))
    monkeypatch.setenv("ARGOS_DBX_EXPERIMENTS", "/a, /b")
    monkeypatch.setenv("ARGOS_DBX_WAREHOUSE_AUTOSTART", "true")
    monkeypatch.setenv("ARGOS_DBX_TRIGGERABLE_JOBS", "extra-job")
    s = DatabricksSettings.from_env()
    assert s.experiments == ("/a", "/b") and s.warehouse_autostart
    assert s.model("q") == MODEL and s.model("nope") is None
    assert s.triggerable_jobs == {"train-q", "extra-job"}


# ------------------------------------------------------------------ connector


def test_approved_alias_and_served_are_distinct(connector):
    status = connector.model_status("q")
    assert status.aliases == {"champion": "2", "challenger": "1"}
    assert status.served == {"ep": "1"}
    by_version = {v.version.version: v for v in status.versions}
    assert by_version["2"].approved and not by_version["1"].approved
    assert by_version["1"].served_by == ["ep"] and by_version["2"].served_by == []


def test_alias_guard_and_unknown_model(connector):
    with pytest.raises(ForbiddenOperationError):
        connector.set_alias("q", "production", "1")
    with pytest.raises(ResourceNotFoundError):
        connector.model_status("unknown")
    connector.set_alias("q", "champion", "1")
    connector.mlflow.set_registered_model_alias.assert_called_once_with(
        "cat.sch.q", "champion", "1"
    )


def test_trigger_job_guards(connector):
    with pytest.raises(ForbiddenOperationError):
        connector.trigger_job("other-job")
    connector.w.jobs.list.return_value = [SimpleNamespace(job_id=7)]
    connector.w.jobs.list_runs.return_value = [SimpleNamespace(run_id=1)]
    with pytest.raises(ConflictError):  # an active run already exists
        connector.trigger_job("train-q")
    connector.w.jobs.run_now.assert_not_called()


def test_errors_are_translated(connector):
    class NotFound(Exception):
        pass

    connector.mlflow.get_run.side_effect = NotFound("RESOURCE_DOES_NOT_EXIST: Run 'x' not found")
    with pytest.raises(ResourceNotFoundError):
        connector.get_run("x")


def test_monitoring_never_starts_a_stopped_warehouse(connector):
    report = connector.monitoring("q")
    assert not report.available and "STOPPED" in report.reason
    connector.w.warehouses.start.assert_not_called()
    connector.w.statement_execution.execute_statement.assert_not_called()


def test_metric_history_deduplicated(connector):
    point = SimpleNamespace(key="m", value=0.5, step=0, timestamp=1_700_000_000_000)
    connector.mlflow.get_metric_history.return_value = [point, point]
    assert len(connector.metric_history("r1", "m")) == 1


# ------------------------------------------------------------------ API router


@pytest.fixture
def api(connector):
    app = FastAPI()
    app.include_router(routes.create_mlops_router(lambda: connector), prefix="/api")
    return TestClient(app)


def test_overview_matches_argos_ui_shape(api):
    body = api.get("/api/models/overview").json()
    assert set(body) >= {
        "threshold",
        "counts",
        "series",
        "drifts",
        "models",
        "training",
        "retrainMode",
    }
    model = body["models"][0]
    assert {"id", "name", "useCase", "scope", "version", "healthPct"} <= set(model)
    assert (
        model["servedVersion"] == "1"
        and model["championVersion"] == "2"
        and model["version"] == "v1"
    )
    assert (
        model["healthPct"] == 80
    )  # validation accuracy of the served run (monitoring unavailable)
    assert body["training"]["absentStoppedPct"] is None  # never invented
    assert any("monitoring" in u for u in body["dataStatus"]["unavailable"])


def test_routes_and_error_codes(api, connector):
    assert api.get("/api/mlops/models/q/status").status_code == 200
    assert api.get("/api/mlops/models/nope/status").status_code == 404
    assert (
        api.post("/api/mlops/models/q/aliases/production", json={"version": "1"}).status_code == 403
    )
    assert api.post("/api/mlops/jobs/other/run").status_code == 403
    response = api.post("/api/models/q/promote", json={"version": "1"})
    assert response.status_code == 200 and response.json()["served"] == {"ep": "1"}
    assert api.put("/api/models/retrain-mode", json={"mode": "AUTO"}).status_code == 204
    assert api.get("/api/models/overview").json()["retrainMode"] == "AUTO"
    assert api.put("/api/models/retrain-mode", json={"mode": "MANUEL"}).status_code == 204


# ------------------------------------------------------------------ inference adapter


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


@pytest.fixture
def endpoint_client(connector):
    client = EndpointClient("ep", workspace=connector.w, timeout_s=5)
    connector.w.config.authenticate.return_value = {"Authorization": "Bearer never-printed"}
    return client


def test_endpoint_prediction_is_normalized(endpoint_client, monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: FakeResponse(
            200, {"predictions": [{"class": "NOK", "anomaly_score": 0.93}]}
        ),
    )
    prediction = endpoint_client.predict(np.zeros((8, 8, 3), np.uint8))
    assert prediction.predicted_class == "NOK" and prediction.anomaly_score == 0.93
    assert prediction.served_version == "1" and prediction.model == "cat.sch.q"


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(503, {"error": "busy"}),
        FakeResponse(200, {"predictions": []}),
        FakeResponse(200, {"predictions": [{"class": "OK", "anomaly_score": 1.7}]}),
    ],
)
def test_endpoint_failures_raise(endpoint_client, monkeypatch, response):
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    with pytest.raises(InferenceError):
        endpoint_client.predict(b"png")


def test_timeout_raises(endpoint_client, monkeypatch):
    def timeout(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "post", timeout)
    with pytest.raises(InferenceError):
        endpoint_client.predict(b"png")


def test_analyzer_returns_the_argos_contract(endpoint_client, monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: FakeResponse(200, {"predictions": [{"class": "OK", "anomaly_score": 0.1}]}),
    )
    analyzer = DatabricksQualityAnalyzer()
    analyzer.client = endpoint_client  # load() would build a real client
    result = analyzer.analyze(
        np.zeros((8, 8, 3), np.uint8), FrameMeta(frame_id="f", workstation_id="W", camera_id="C")
    )
    assert isinstance(result, AnalysisResult) and isinstance(result.details, QualityDetails)
    assert result.score == 0.1 and result.model_version == "1"
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
