"""MLOps API over Databricks, as ONE reusable FastAPI router.

Mount it under ``/api`` (standalone: ``mlops.api.app``; later in the Core:
``app.include_router(create_mlops_router(), prefix="/api")`` — no Core file is changed here).

Two groups of routes:
- ``/models/...``  : exactly what the argos-ui AI Leader screen calls today
  (overview, retrain, retrain-mode, promote);
- ``/mlops/...``   : detailed, typed reads and the few writes the AI Leader needs.

Approval, alias and served version are three distinct things everywhere:
``POST /mlops/models/{id}/versions/{v}/approve`` tags a version as approved,
``POST /models/{id}/promote`` / ``POST /mlops/models/{id}/aliases/{alias}`` move a UC alias,
and only the serving endpoint configuration decides what is served (not changed here).
"""

import functools
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from mlops.connectors.mlflow_client import ExperimentInfo, MetricPoint, ModelVersionInfo, RunSummary
from mlops.databricks.connector import (
    ConnectionStatus,
    DatabricksConnector,
    DatabricksConnectorError,
    EndpointInfo,
    JobInfo,
    JobRunInfo,
    ModelStatus,
    MonitoringReport,
    SchemaInfo,
    VersionStatus,
)
from mlops.databricks.training import DatabricksJobBackend
from visionhub.contracts import UseCase
from visionhub.integration.mlops import ModelRef, RetrainingPolicy

HEALTH_THRESHOLD = 85


class PromoteBody(BaseModel):
    version: str


class AliasBody(BaseModel):
    version: str


class RetrainModeBody(BaseModel):
    mode: Literal["MANUEL", "AUTO"]


def translate(fn: Callable) -> Callable:
    """Connector errors -> HTTP errors (503 unavailable, 404, 403, 409, 502)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatabricksConnectorError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    return wrapper


@functools.lru_cache(maxsize=1)
def default_connector() -> DatabricksConnector:
    return DatabricksConnector()


# In-memory retraining policies (one per ARGOS use case). Persisting them is the Core's job.
_POLICIES: dict[str, RetrainingPolicy] = {}


def _policy_mode() -> Literal["MANUEL", "AUTO"]:
    return "AUTO" if any(p.auto_train for p in _POLICIES.values()) else "MANUEL"


def create_mlops_router(
    get_connector: Callable[[], DatabricksConnector] = default_connector,
) -> APIRouter:
    router = APIRouter(tags=["mlops"])
    Connector = Annotated[DatabricksConnector, Depends(get_connector)]

    # ------------------------------------------------------------------ argos-ui (AI Leader)

    @router.get("/models/overview")
    @translate
    def models_overview(c: Connector) -> dict[str, Any]:
        """argos-ui ``AiOverview``, filled with real Databricks data where it exists."""
        return build_overview(c)

    @router.post("/models/{model_id}/retrain", status_code=202)
    @translate
    def retrain(model_id: str, c: Connector) -> JobRunInfo:
        return DatabricksJobBackend(c).submit(model_id)

    @router.put("/models/retrain-mode", status_code=204)
    @translate
    def retrain_mode(body: RetrainModeBody, c: Connector) -> None:
        for managed in c.settings.models:
            _POLICIES[managed.argos_use_case] = RetrainingPolicy(
                use_case=UseCase(managed.argos_use_case),
                enabled=True,
                auto_train=body.mode == "AUTO",
            )

    @router.post("/models/{model_id}/promote")
    @translate
    def promote(model_id: str, body: PromoteBody, c: Connector) -> ModelStatus:
        """Moves the ``champion`` alias. The served version is NOT changed (see ``served``)."""
        return c.set_alias(model_id, "champion", body.version)

    # ------------------------------------------------------------------ detailed reads

    @router.get("/mlops/health")
    @translate
    def health(c: Connector) -> ConnectionStatus:
        return c.ping()

    @router.get("/mlops/catalogs")
    @translate
    def catalogs(c: Connector) -> list[str]:
        return c.list_catalogs()

    @router.get("/mlops/catalogs/{catalog}/schemas")
    @translate
    def schemas(catalog: str, c: Connector) -> list[SchemaInfo]:
        return c.list_schemas(catalog)

    @router.get("/mlops/experiments")
    @translate
    def experiments(c: Connector) -> list[ExperimentInfo]:
        return c.list_experiments()

    @router.get("/mlops/experiments/{experiment_id}/runs")
    @translate
    def runs(
        experiment_id: str, c: Connector, limit: int = Query(50, ge=1, le=500)
    ) -> list[RunSummary]:
        return c.list_runs(experiment_id, limit)

    @router.get("/mlops/runs/compare")
    @translate
    def compare(
        c: Connector, ids: str = Query(..., description="comma-separated run ids")
    ) -> dict[str, Any]:
        return c.compare_runs([i for i in ids.split(",") if i])

    @router.get("/mlops/runs/{run_id}")
    @translate
    def run(run_id: str, c: Connector) -> RunSummary:
        return c.get_run(run_id)

    @router.get("/mlops/runs/{run_id}/metrics/{key}/history")
    @translate
    def history(run_id: str, key: str, c: Connector) -> list[MetricPoint]:
        return c.metric_history(run_id, key)

    @router.get("/mlops/models")
    @translate
    def models(c: Connector) -> list[dict[str, Any]]:
        return [m.model_dump() for m in c.settings.models]

    @router.get("/mlops/models/{model_id}/versions")
    @translate
    def versions(model_id: str, c: Connector) -> list[ModelVersionInfo]:
        return c.model_versions(model_id)

    @router.get("/mlops/models/{model_id}/status")
    @translate
    def status(model_id: str, c: Connector) -> ModelStatus:
        return c.model_status(model_id)

    @router.get("/mlops/models/{model_id}/aliases/{alias}")
    @translate
    def alias(model_id: str, alias: str, c: Connector) -> ModelRef:
        return c.resolve_alias(model_id, alias)

    @router.post("/mlops/models/{model_id}/aliases/{alias}")
    @translate
    def set_alias(model_id: str, alias: str, body: AliasBody, c: Connector) -> ModelStatus:
        return c.set_alias(model_id, alias, body.version)

    @router.post("/mlops/models/{model_id}/versions/{version}/approve")
    @translate
    def approve(model_id: str, version: str, c: Connector) -> VersionStatus:
        return c.approve_version(model_id, version)

    @router.get("/mlops/models/{model_id}/monitoring")
    @translate
    def monitoring(model_id: str, c: Connector, refresh: bool = False) -> MonitoringReport:
        return c.monitoring(model_id, refresh=refresh)

    @router.get("/mlops/jobs")
    @translate
    def jobs(c: Connector) -> list[JobInfo]:
        return c.list_jobs()

    @router.get("/mlops/jobs/{job_id}/runs")
    @translate
    def job_runs(
        job_id: int, c: Connector, limit: int = Query(10, ge=1, le=100)
    ) -> list[JobRunInfo]:
        return c.job_runs(job_id, limit)

    @router.post("/mlops/jobs/{job_name}/run", status_code=202)
    @translate
    def trigger(job_name: str, c: Connector) -> JobRunInfo:
        return c.trigger_job(job_name)

    @router.get("/mlops/job-runs/{run_id}")
    @translate
    def job_run(run_id: int, c: Connector) -> JobRunInfo:
        return c.get_job_run(run_id)

    @router.get("/mlops/endpoints")
    @translate
    def endpoints(c: Connector) -> list[EndpointInfo]:
        return c.list_endpoints()

    @router.get("/mlops/endpoints/{name}")
    @translate
    def endpoint(name: str, c: Connector) -> EndpointInfo:
        return c.get_endpoint(name)

    return router


# --------------------------------------------------------------------------- overview


def _pct(value: float | None) -> int | None:
    return None if value is None else round(100 * value)


def build_overview(c: DatabricksConnector) -> dict[str, Any]:
    """Build argos-ui ``AiOverview``. Fields with no real source are null / empty and
    listed in ``dataStatus.unavailable`` (never invented)."""
    models, drifts, unavailable = (
        [],
        [],
        [
            "series (no daily health history yet)",
            "training.absentStoppedPct / doubleStoppedPct (product-specific)",
        ],
    )
    training = None
    for managed in c.settings.models:
        status = c.model_status(managed.id)
        served = next((v for v in status.served.values() if v), None)
        current = served or status.aliases.get("champion")
        version = next((v for v in status.versions if v.version.version == current), None)
        run = c.get_run(version.version.run_id) if version and version.version.run_id else None
        monitoring = c.monitoring(managed.id)
        accuracy = monitoring.accuracies.get("accuracy_reference") if monitoring.available else None
        health = (
            _pct(accuracy)
            if accuracy is not None
            else _pct(run.metrics.get("val_accuracy") if run else None)
        )
        models.append(
            {
                "id": managed.id,
                "name": managed.display_name,
                "useCase": managed.use_case,
                "scope": managed.scope,
                "version": f"v{current}" if current else "—",
                "healthPct": health,
                "recallKoPct": _pct(
                    run.metrics.get("test_recall_nok", run.metrics.get("val_recall_nok"))
                    if run
                    else None
                ),
                "servedVersion": served,
                "championVersion": status.aliases.get("champion"),
                "approvedVersions": [v.version.version for v in status.versions if v.approved],
                "synthetic": managed.synthetic,
            }
        )
        if (
            monitoring.available
            and monitoring.metrics
            and any(d.alert for d in monitoring.metrics.drift)
        ):
            alerts = ", ".join(
                f"{d.feature} PSI {d.value:.2f}" for d in monitoring.metrics.drift if d.alert
            )
            drifts.append(
                {
                    "modelId": managed.id,
                    "title": managed.display_name,
                    "detail": f"Dérive des données détectée : {alerts} (seuil 0,2)",
                    "healthPct": health,
                    "mode": _policy_mode(),
                }
            )
        elif not monitoring.available:
            unavailable.append(f"monitoring {managed.id}: {monitoring.reason}")
        if training is None and status.versions:
            latest = status.versions[-1]
            previous = status.versions[-2] if len(status.versions) > 1 else None
            latest_run = c.get_run(latest.version.run_id) if latest.version.run_id else None
            previous_run = (
                c.get_run(previous.version.run_id) if previous and previous.version.run_id else None
            )
            step = 5 if latest.served_by else 4
            training = {
                "modelName": managed.display_name,
                "version": f"v{latest.version.version}",
                "dataset": (latest_run.params.get("dataset_version") if latest_run else None)
                or "—",
                "step": step,
                "recallKoPct": _pct(
                    latest_run.metrics.get("test_recall_nok") if latest_run else None
                ),
                "previousRecallKoPct": _pct(
                    previous_run.metrics.get("test_recall_nok") if previous_run else None
                ),
                "absentStoppedPct": None,
                "doubleStoppedPct": None,
            }
    healths = [m["healthPct"] for m in models if m["healthPct"] is not None]
    return {
        "threshold": HEALTH_THRESHOLD,
        "counts": {
            "healthy": sum(h >= 90 for h in healths),
            "watch": sum(HEALTH_THRESHOLD <= h < 90 for h in healths),
            "retrain": sum(h < HEALTH_THRESHOLD for h in healths),
        },
        "series": [],
        "drifts": drifts,
        "models": models,
        "training": training,
        "retrainMode": _policy_mode(),
        "dataStatus": {
            "source": "Databricks (MLflow, Unity Catalog, Jobs, Serving, Delta monitoring)",
            "healthPct": "labelled accuracy of the last monitoring window, "
            "else validation accuracy of the served run",
            "unavailable": unavailable,
        },
    }
