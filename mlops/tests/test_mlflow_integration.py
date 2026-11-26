"""Integration tests against a REAL MLflow server (opt-in: ARGOS_MLFLOW_IT=1).

They use their OWN experiment and registered model (random suffix) and remove them at the
end: the demo data (argos-foundation-demo*) is never touched.
"""

import uuid

import mlflow
import mlflow.pyfunc
import mlflow.sklearn
import numpy as np
import pytest
from mlflow.models import infer_signature
from sklearn.linear_model import LogisticRegression

from mlops.config import MlflowSettings
from mlops.connectors import (
    AliasNotFoundError,
    ArgosMlflowConnector,
    ExperimentNotFoundError,
    ModelVersionNotFoundError,
    RunNotFoundError,
    ServerUnavailableError,
)
from mlops.demo.data import make_dataset
from mlops.demo.training import evaluate

pytestmark = pytest.mark.mlflow_server

SUFFIX = uuid.uuid4().hex[:8]
EXPERIMENT = f"argos-foundation-it-{SUFFIX}"
MODEL = f"argos-foundation-demo-it-{SUFFIX}"


@pytest.fixture(scope="module")
def connector():
    return ArgosMlflowConnector(MlflowSettings.from_env())


@pytest.fixture(scope="module")
def trained(connector, tmp_path_factory):
    """Two real (tiny) trainings logged to a dedicated experiment."""
    settings = connector.settings
    mlflow.set_tracking_uri(settings.tracking_uri)
    mlflow.set_registry_uri(settings.registry_uri)
    experiment = mlflow.set_experiment(EXPERIMENT)
    data = make_dataset()
    results = []
    for c in (0.1, 1.0):
        with mlflow.start_run(run_name=f"it-logreg-C{c}") as run:
            mlflow.set_tags({"synthetic": "true", "argos.test": "integration"})
            mlflow.log_params({"C": c, "seed": 0})
            model = LogisticRegression(C=c, max_iter=300, random_state=0).fit(
                data.X_train, data.y_train
            )
            for step in range(3):
                mlflow.log_metric("it_curve", float(step) / 10, step=step)
            metrics, report, _ = evaluate(model, data.X_val, data.y_val, "val")
            mlflow.log_dict(report, "reports/classification_report.json")
            info = mlflow.sklearn.log_model(
                model,
                name="model",
                signature=infer_signature(data.X_val.head(5), model.predict(data.X_val.head(5))),
            )
            mlflow.log_metrics(metrics, model_id=info.model_id)
            results.append(
                {"run_id": run.info.run_id, "model_id": info.model_id, "metrics": metrics}
            )
    yield {"experiment_id": experiment.experiment_id, "runs": results, "data": data}
    # Cleanup of OUR objects only.
    client = connector.client
    try:
        client.delete_registered_model(MODEL)
    except Exception:  # noqa: BLE001 - best effort cleanup
        pass
    client.delete_experiment(experiment.experiment_id)


def test_server_answers(connector):
    status = connector.ping()
    assert status.healthy and status.version == "3.18.0"


def test_experiment_runs_metrics_history(connector, trained):
    experiment = connector.get_experiment(EXPERIMENT)
    assert experiment.experiment_id == trained["experiment_id"]
    runs = connector.list_runs(EXPERIMENT)
    assert {r.run_id for r in runs} == {r["run_id"] for r in trained["runs"]}
    run_id = trained["runs"][0]["run_id"]
    assert connector.get_run_params(run_id)["C"] == "0.1"
    assert connector.get_run_metrics(run_id)["val_f1_macro"] == pytest.approx(
        trained["runs"][0]["metrics"]["val_f1_macro"]
    )
    assert [p.step for p in connector.get_metric_history(run_id, "it_curve")] == [0, 1, 2]


def test_artifact_list_and_download(connector, trained):
    run_id = trained["runs"][0]["run_id"]
    assert "reports/classification_report.json" in {
        a.path for a in connector.list_artifacts(run_id, "reports")
    }
    path = connector.download_artifact(run_id, "reports/classification_report.json")
    assert path.exists() and path.read_text(encoding="utf-8").startswith("{")


def test_registry_versions_aliases_and_prediction(connector, trained):
    first, second = trained["runs"]
    v1 = connector.register_demo_model(MODEL, first["model_id"])
    v2 = connector.register_demo_model(MODEL, second["model_id"])
    assert (v1.version, v2.version) == ("1", "2")
    assert v1.run_id == first["run_id"] and v1.model_id == first["model_id"]

    assert connector.set_demo_alias(MODEL, "champion", 1).version == "1"
    connector.set_demo_alias(MODEL, "challenger", 2)
    assert connector.resolve(f"models:/{MODEL}@champion").version == "1"
    assert connector.resolve(f"models:/{MODEL}/2").aliases == ["challenger"]
    assert [v.aliases for v in connector.list_model_versions(MODEL)] == [
        ["champion"],
        ["challenger"],
    ]
    ref = connector.to_model_ref(connector.resolve_alias(MODEL, "champion"), "champion")
    assert ref.uri == f"models:/{MODEL}/1" and ref.mlflow_run_id == first["run_id"]

    connector.set_demo_alias(MODEL, "champion", 2)  # move the alias
    assert connector.resolve_alias(MODEL, "champion").version == "2"

    data = trained["data"]
    model = mlflow.pyfunc.load_model(f"models:/{MODEL}@champion")
    predictions = np.asarray(model.predict(data.X_test.head(20)))
    assert predictions.shape == (20,) and set(predictions) <= {0, 1, 2}


def test_errors_against_the_real_server(connector, trained):
    with pytest.raises(ExperimentNotFoundError):
        connector.get_experiment(f"no-such-experiment-{SUFFIX}")
    with pytest.raises(RunNotFoundError):
        connector.get_run("0" * 32)
    with pytest.raises(ModelVersionNotFoundError):
        connector.get_model_version(MODEL, 99)
    with pytest.raises(AliasNotFoundError):
        connector.resolve_alias(MODEL, "no-such-alias")


def test_unreachable_server_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    dead = MlflowSettings(
        tracking_uri="http://127.0.0.1:59999",
        registry_uri="http://127.0.0.1:59999",
        mlops_home=tmp_path,
        download_dir=tmp_path,
        request_timeout_s=2,
        max_retries=0,
    )
    connector = ArgosMlflowConnector(dead)
    with pytest.raises(ServerUnavailableError):
        connector.ping()
    with pytest.raises(ServerUnavailableError):
        connector.list_experiments()
