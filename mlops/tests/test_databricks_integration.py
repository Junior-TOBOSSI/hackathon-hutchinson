"""DBX-01 integration tests against the REAL Databricks workspace (opt-in, read-only).

    $env:ARGOS_DBX_IT = "1"
    <mlops venv python> -m pytest mlops/tests/test_databricks_integration.py

Read-only by default: no job run, no warehouse start, no remote inference. One remote
inference is added only with ARGOS_DBX_IT_INFERENCE=1.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ARGOS_DBX_IT") != "1", reason="set ARGOS_DBX_IT=1")


@pytest.fixture(scope="module")
def connector():
    from mlops.databricks.connector import DatabricksConnector

    return DatabricksConnector()


@pytest.fixture(scope="module")
def api(connector):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mlops.api.routes import create_mlops_router

    app = FastAPI()
    app.include_router(create_mlops_router(lambda: connector), prefix="/api")
    return TestClient(app)


def test_connection_and_catalog(connector):
    assert connector.ping().user_active
    assert "workspace" in connector.list_catalogs()


def test_experiments_runs_and_registry(api):
    experiments = api.get("/api/mlops/experiments").json()
    assert experiments, "configured experiment not found"
    runs = api.get(f"/api/mlops/experiments/{experiments[0]['experiment_id']}/runs").json()
    assert runs and all("val_f1_nok" in r["metrics"] for r in runs)
    status = api.get("/api/mlops/models/quality-poc/status").json()
    assert {"champion", "challenger"} <= set(status["aliases"])
    assert list(status["served"].values())[0] in {
        v["version"]["version"] for v in status["versions"]
    }


def test_jobs_endpoints_overview(api):
    jobs = api.get("/api/mlops/jobs").json()
    assert any(j["triggerable"] for j in jobs) and not any(j["scheduled"] for j in jobs)
    endpoint = api.get("/api/mlops/endpoints/argos-quality-poc").json()
    assert endpoint["served"][0]["scale_to_zero"] is True
    overview = api.get("/api/models/overview").json()
    assert overview["models"][0]["servedVersion"] == endpoint["served"][0]["version"]


@pytest.mark.skipif(
    os.environ.get("ARGOS_DBX_IT_INFERENCE") != "1", reason="set ARGOS_DBX_IT_INFERENCE=1"
)
def test_one_remote_inference():
    import numpy as np

    from mlops.databricks.inference import EndpointClient

    prediction = EndpointClient("argos-quality-poc", timeout_s=60).predict(
        np.zeros((64, 64, 3), np.uint8)
    )
    assert 0.0 <= prediction.anomaly_score <= 1.0 and prediction.served_version
