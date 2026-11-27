"""Unit tests of the ARGOS MLflow connector: the MLflow client is mocked, no server needed."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, INVALID_STATE, RESOURCE_DOES_NOT_EXIST

from mlops.config import MlflowSettings
from mlops.connectors import (
    AliasNotFoundError,
    ArgosMlflowConnector,
    ArtifactDownloadError,
    ExperimentNotFoundError,
    ForbiddenOperationError,
    MlflowConnectorError,
    ModelVersionNotFoundError,
    RegisteredModelNotFoundError,
    RunNotFoundError,
    ServerUnavailableError,
)
from visionhub.integration.mlops import ModelRef

MISSING = MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST)
DOWN = MlflowException(
    "API request to http://127.0.0.1:5000/api/2.0/mlflow/runs/get failed with exception "
    "HTTPConnectionPool(host='127.0.0.1', port=5000): Max retries exceeded",
    error_code=INTERNAL_ERROR,
)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for key in (
        "MLFLOW_HTTP_REQUEST_TIMEOUT",
        "MLFLOW_HTTP_REQUEST_MAX_RETRIES",
        "MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR",
    ):
        monkeypatch.setenv(key, "0")  # restored after each test
    return MlflowSettings(mlops_home=tmp_path, download_dir=tmp_path / "downloads")


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def connector(settings, client):
    return ArgosMlflowConnector(settings, client)


def run(run_id="r1"):
    return SimpleNamespace(
        info=SimpleNamespace(
            run_id=run_id,
            run_name="rf",
            experiment_id="1",
            status="FINISHED",
            start_time=1_700_000_000_000,
            end_time=None,
            artifact_uri="mlflow-artifacts:/1/r1/artifacts",
        ),
        data=SimpleNamespace(
            params={"seed": "7"}, metrics={"val_f1_macro": 0.8}, tags={"synthetic": "true"}
        ),
    )


def version(number="1", aliases=(), tags=None):
    return SimpleNamespace(
        name="argos-foundation-demo-model",
        version=number,
        aliases=list(aliases),
        run_id="r1",
        model_id=None,
        source="mlflow-artifacts:/1/models/m-1/artifacts",
        status="READY",
        tags=tags or {},
        creation_timestamp=1_700_000_000_000,
    )


def registered(aliases=None):
    return SimpleNamespace(
        name="argos-foundation-demo-model",
        description=None,
        tags={},
        aliases=aliases or {},
        latest_versions=[],
        creation_timestamp=None,
    )


# ------------------------------------------------------------------ configuration


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://tracking:5000")
    monkeypatch.delenv("MLFLOW_REGISTRY_URI", raising=False)
    monkeypatch.setenv("ARGOS_MLOPS_HOME", str(tmp_path))
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "4")
    settings = MlflowSettings.from_env()
    assert settings.registry_uri == "http://tracking:5000"  # defaults to the tracking URI
    assert settings.download_dir == tmp_path / "downloads"
    assert settings.request_timeout_s == 4
    monkeypatch.setenv("MLFLOW_REGISTRY_URI", "http://registry:5001")
    assert MlflowSettings.from_env().registry_uri == "http://registry:5001"


def test_http_policy_is_applied_to_the_process(connector):
    import os

    assert os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] == "10"
    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "2"


# ------------------------------------------------------------------ errors


def test_server_down_is_explicit(connector, client):
    client.search_experiments.side_effect = DOWN
    with pytest.raises(ServerUnavailableError):
        connector.list_experiments()
    client.get_run.side_effect = requests.ConnectionError("refused")
    with pytest.raises(ServerUnavailableError):
        connector.get_run("r1")


def test_ping_down(connector, monkeypatch):
    def refuse(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", refuse)
    with pytest.raises(ServerUnavailableError):
        connector.ping()


def test_unknown_resources(connector, client):
    client.get_experiment_by_name.return_value = None
    with pytest.raises(ExperimentNotFoundError):
        connector.get_experiment("no-such-experiment")
    client.get_experiment.side_effect = MISSING
    with pytest.raises(ExperimentNotFoundError):
        connector.get_experiment("999")
    client.get_run.side_effect = MISSING
    with pytest.raises(RunNotFoundError):
        connector.get_run("nope")
    with pytest.raises(RunNotFoundError):  # MLflow itself would return [] here
        connector.get_metric_history("nope", "val_accuracy")
    client.get_metric_history.assert_not_called()
    client.get_registered_model.side_effect = MISSING
    with pytest.raises(RegisteredModelNotFoundError):
        connector.get_registered_model("nope")


def test_unknown_version_and_alias(connector, client):
    client.get_registered_model.return_value = registered({"champion": "1"})
    client.get_model_version.side_effect = MISSING
    with pytest.raises(ModelVersionNotFoundError):
        connector.get_model_version("argos-foundation-demo-model", 9)
    with pytest.raises(AliasNotFoundError):
        connector.resolve_alias("argos-foundation-demo-model", "staging")
    client.get_model_version_by_alias.assert_not_called()


def test_other_mlflow_errors_are_wrapped(connector, client):
    client.search_registered_models.side_effect = MlflowException("boom", error_code=INVALID_STATE)
    with pytest.raises(MlflowConnectorError):
        connector.list_registered_models()


# ------------------------------------------------------------------ reads


def test_run_reads(connector, client):
    client.get_run.return_value = run()
    assert connector.get_run_params("r1") == {"seed": "7"}
    assert connector.get_run_metrics("r1") == {"val_f1_macro": 0.8}
    client.get_metric_history.return_value = [
        SimpleNamespace(key="acc", value=0.9, step=2, timestamp=2),
        SimpleNamespace(key="acc", value=0.8, step=1, timestamp=1),
    ]
    assert [p.step for p in connector.get_metric_history("r1", "acc")] == [1, 2]


def test_list_versions_merges_aliases_and_logged_model(connector, client):
    client.get_registered_model.return_value = registered({"champion": "2", "challenger": "1"})
    client.search_model_versions.return_value = [
        version("2", tags={"argos.logged_model_id": "m-2"}),
        version("1"),
    ]
    versions = connector.list_model_versions("argos-foundation-demo-model")
    assert [(v.version, v.aliases) for v in versions] == [
        ("1", ["challenger"]),
        ("2", ["champion"]),
    ]
    assert versions[1].model_id == "m-2"
    assert versions[1].uri == "models:/argos-foundation-demo-model/2"


def test_resolve_uris(connector, client):
    client.get_registered_model.return_value = registered({"champion": "2"})
    client.get_model_version.return_value = version("1")
    client.get_model_version_by_alias.return_value = version("2", aliases=["champion"])
    assert connector.resolve("models:/argos-foundation-demo-model/1").version == "1"
    assert connector.resolve("models:/argos-foundation-demo-model@champion").version == "2"
    for bad in ("runs:/r1/model", "models:/argos-foundation-demo-model/latest", "models:/x"):
        with pytest.raises(ValueError):
            connector.resolve(bad)


def test_model_ref_uses_the_argos_contract(connector):
    ref = connector.to_model_ref(connector_version := _info(), alias="champion")
    assert ref == ModelRef(
        registered_model=connector_version.name, version="1", alias="champion", mlflow_run_id="r1"
    )
    assert ref.uri == "models:/argos-foundation-demo-model/1"


def _info():
    from mlops.connectors.mlflow_client import _version

    return _version(version("1"))


# ------------------------------------------------------------------ artifacts


def test_download_outside_allowed_folder_is_refused(connector, client, tmp_path):
    with pytest.raises(ArtifactDownloadError):
        connector.download_artifact("r1", "reports/x.json", tmp_path / "elsewhere")
    client.download_artifacts.assert_not_called()


def test_download_success_and_failure(connector, client, settings):
    client.get_run.return_value = run()
    expected = settings.download_dir / "r1" / "x.json"
    client.download_artifacts.return_value = str(expected)
    assert connector.download_artifact("r1", "x.json") == Path(expected)
    client.download_artifacts.side_effect = MlflowException("disk full", error_code=INTERNAL_ERROR)
    with pytest.raises(ArtifactDownloadError):
        connector.download_artifact("r1", "x.json")


# ------------------------------------------------------------------ demo writes


@pytest.mark.parametrize("name", ["argos-quality", "production-model", "argos-foundation"])
def test_registry_writes_are_limited_to_demo_models(connector, client, name):
    with pytest.raises(ForbiddenOperationError):
        connector.set_demo_alias(name, "champion", 1)
    with pytest.raises(ForbiddenOperationError):
        connector.register_demo_model(name, "m-1")
    client.set_registered_model_alias.assert_not_called()
    client.create_model_version.assert_not_called()


def test_register_demo_model_keeps_the_training_link(connector, client):
    client.get_logged_model.return_value = SimpleNamespace(
        artifact_location="mlflow-artifacts:/1/models/m-1/artifacts", source_run_id="r1"
    )
    client.get_registered_model.side_effect = MISSING
    client.create_model_version.return_value = version("1", tags={"argos.logged_model_id": "m-1"})
    created = connector.register_demo_model("argos-foundation-demo-model", "m-1", tags={"k": "v"})
    client.create_registered_model.assert_called_once()
    kwargs = client.create_model_version.call_args.kwargs
    assert kwargs["run_id"] == "r1" and kwargs["model_id"] == "m-1"
    assert (
        kwargs["tags"]["argos.logged_model_id"] == "m-1" and kwargs["tags"]["synthetic"] == "true"
    )
    assert created.model_id == "m-1"
