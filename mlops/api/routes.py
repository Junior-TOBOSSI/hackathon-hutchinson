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
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel

from mlops.api.monitoring_routes import create_monitoring_router
from mlops.api.retraining_routes import create_retraining_router
from mlops.api.training_routes import create_training_router
from mlops.api.training_routes import service_for as training_service_for
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
from mlops.databricks.datasets import (
    DatasetFamilySummary,
    DatasetIndex,
    DatasetVersionSummary,
    ImportResult,
    ItemPage,
    PublishJob,
    TableInfo,
    TrainingDataset,
    dataset_store,
)
from mlops.databricks.read_cache import BudgetExceeded, fresh_reads, read_scope
from mlops.deployment.contracts import LifecycleError
from mlops.training.service import LaunchRecord, remote_enabled
from visionhub.contracts import UseCase
from visionhub.integration.mlops import ModelRef, RetrainingPolicy

HEALTH_THRESHOLD = 85


class PromoteBody(BaseModel):
    version: str


class AliasBody(BaseModel):
    version: str


class LegacyRetrainBody(BaseModel):
    """Optional body of the legacy route: without dataset, version and idempotency key the
    request is refused (no implicit choice of training data)."""

    pipeline_id: str | None = None
    dataset_id: str | None = None
    version: str | None = None
    parameters: dict[str, Any] = {}
    idempotency_key: str | None = None


class RetrainModeBody(BaseModel):
    mode: Literal["MANUEL", "AUTO"]


class DraftBody(BaseModel):
    parent_version: str


class FamilyBody(BaseModel):
    dataset_id: str
    name: str
    use_case: str
    classes: list[str]
    synthetic: bool = True
    description: str | None = None


class FamilyDraftBody(BaseModel):
    parent_version: str | None = None


class ItemChange(BaseModel):
    file: str
    action: Literal["validate", "relabel", "exclude", "reset"]
    label: str | None = None
    note: str | None = None


class ItemChanges(BaseModel):
    changes: list[ItemChange]


class PublishBody(BaseModel):
    version: str


IMMUTABLE_IMAGE = {"Cache-Control": "private, max-age=31536000, immutable"}


def translate(fn: Callable) -> Callable:
    """Connector errors -> HTTP errors (503 unavailable, 404, 403, 409, 502)."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatabricksConnectorError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except LifecycleError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(503, f"Databricks too slow: {exc}") from exc

    return wrapper


_CONNECTOR: DatabricksConnector | None = None
_CONNECTOR_LOCK = threading.Lock()


def default_connector() -> DatabricksConnector:
    """One connector per process, built once even under concurrent first requests
    (warm-up thread + browser requests)."""
    global _CONNECTOR
    if _CONNECTOR is None:
        with _CONNECTOR_LOCK:
            if _CONNECTOR is None:
                _CONNECTOR = DatabricksConnector()
    return _CONNECTOR


T = TypeVar("T")


def served(c: DatabricksConnector, response: Response, fresh: bool, read: Callable[[], T]) -> T:
    """Run a read inside a request scope: bounded total time, ``fresh`` = bypass the cache,
    and freshness headers computed from the REAL remote reads used by the response."""
    with read_scope(fresh=fresh, budget=c.settings.request_budget_seconds) as scope:
        result = read()
    response.headers.update(scope.headers())
    return result


Fresh = Annotated[bool, Query(description="true = bypass the server cache (real read)")]


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
    def models_overview(c: Connector, response: Response, fresh: Fresh = False) -> dict[str, Any]:
        """argos-ui ``AiOverview``, filled with real Databricks data where it exists."""
        return served(c, response, fresh, lambda: build_overview(c))

    @router.post("/models/{model_id}/retrain", status_code=202)
    @translate
    def retrain(model_id: str, c: Connector, body: LegacyRetrainBody | None = None) -> LaunchRecord:
        """Legacy route kept for compatibility, connected to THE single launch path."""
        svc = training_service_for(c)
        body = body or LegacyRetrainBody()
        if not remote_enabled():
            svc.audit.log(
                outcome="refused_lock", source="legacy:/models/retrain", model_id=model_id
            )
            raise HTTPException(
                403, "remote training launch is not authorized (HOVIS_TRAINING_REMOTE)"
            )
        if not (body.dataset_id and body.version and body.idempotency_key):
            svc.audit.log(
                outcome="refused_incomplete", source="legacy:/models/retrain", model_id=model_id
            )
            raise HTTPException(
                422, "dataset_id, version and idempotency_key are required (use Training Factory)"
            )
        pipeline = body.pipeline_id or svc.pipeline_for_model(model_id).id
        return svc.launch(
            pipeline,
            body.dataset_id,
            body.version,
            body.parameters,
            body.idempotency_key,
            source="legacy:/models/retrain",
        )

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
    def health(c: Connector, response: Response, fresh: Fresh = False) -> ConnectionStatus:
        return served(c, response, fresh, lambda: c.ping())

    @router.get("/mlops/catalogs")
    @translate
    def catalogs(c: Connector, response: Response, fresh: Fresh = False) -> list[str]:
        return served(c, response, fresh, lambda: c.list_catalogs())

    @router.get("/mlops/catalogs/{catalog}/schemas")
    @translate
    def schemas(
        catalog: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> list[SchemaInfo]:
        return served(c, response, fresh, lambda: c.list_schemas(catalog))

    @router.get("/mlops/experiments")
    @translate
    def experiments(c: Connector, response: Response, fresh: Fresh = False) -> list[ExperimentInfo]:
        return served(c, response, fresh, lambda: c.list_experiments())

    @router.get("/mlops/experiments/{experiment_id}/runs")
    @translate
    def runs(
        experiment_id: str,
        c: Connector,
        response: Response,
        fresh: Fresh = False,
        limit: int = Query(50, ge=1, le=500),
    ) -> list[RunSummary]:
        return served(c, response, fresh, lambda: c.list_runs(experiment_id, limit))

    @router.get("/mlops/runs/compare")
    @translate
    def compare(
        c: Connector, ids: str = Query(..., description="comma-separated run ids")
    ) -> dict[str, Any]:
        return c.compare_runs([i for i in ids.split(",") if i])

    @router.get("/mlops/runs/{run_id}")
    @translate
    def run(run_id: str, c: Connector, response: Response, fresh: Fresh = False) -> RunSummary:
        return served(c, response, fresh, lambda: c.get_run(run_id))

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
    def versions(
        model_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> list[ModelVersionInfo]:
        return served(c, response, fresh, lambda: c.model_versions(model_id))

    @router.get("/mlops/models/{model_id}/status")
    @translate
    def status(
        model_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> ModelStatus:
        return served(c, response, fresh, lambda: c.model_status(model_id))

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
        # Keep the existing response while recording the same decision as the new API.
        from mlops.deployment.contracts import DecisionRequest, LifecycleError
        from mlops.deployment.runtime import lifecycle_service

        decision = lifecycle_service(c).decide(
            model_id, version,
            DecisionRequest(
                decision="approved", reason="Legacy approval route",
                author_declared="unknown", role_declared="ai_leader",
            ),
        )
        if decision.status != "applied":
            raise LifecycleError("approval outcome uncertain; inspect decision history", 503)
        with fresh_reads():
            status = c.model_status(model_id)
        return next(v for v in status.versions if v.version.version == version)

    @router.get("/mlops/models/{model_id}/monitoring")
    @translate
    def monitoring(model_id: str, c: Connector, refresh: bool = False) -> MonitoringReport:
        return c.monitoring(model_id, refresh=refresh)

    @router.get("/mlops/jobs")
    @translate
    def jobs(c: Connector, response: Response, fresh: Fresh = False) -> list[JobInfo]:
        return served(c, response, fresh, lambda: c.list_jobs())

    @router.get("/mlops/jobs/{job_id}/runs")
    @translate
    def job_runs(
        job_id: int,
        c: Connector,
        response: Response,
        fresh: Fresh = False,
        limit: int = Query(10, ge=1, le=100),
    ) -> list[JobRunInfo]:
        return served(c, response, fresh, lambda: c.job_runs(job_id, limit))

    @router.post("/mlops/jobs/{job_name}/run", status_code=202)
    @translate
    def trigger(job_name: str, c: Connector) -> JobRunInfo:
        """Non-training allow-listed jobs only, behind HOVIS_TRAINING_REMOTE (journaled)."""
        audit = training_service_for(c).audit
        try:
            run = c.trigger_job(job_name)
        except DatabricksConnectorError as exc:
            audit.log(
                outcome="refused",
                source="route:/mlops/jobs/run",
                job=job_name,
                error=str(exc)[:200],
            )
            raise
        audit.log(
            outcome="submitted", source="route:/mlops/jobs/run", job=job_name, job_run_id=run.run_id
        )
        return run

    @router.get("/mlops/job-runs/{run_id}")
    @translate
    def job_run(run_id: int, c: Connector) -> JobRunInfo:
        return c.get_job_run(run_id)

    @router.get("/mlops/endpoints")
    @translate
    def endpoints(c: Connector, response: Response, fresh: Fresh = False) -> list[EndpointInfo]:
        return served(c, response, fresh, lambda: c.list_endpoints())

    @router.get("/mlops/endpoints/{name}")
    @translate
    def endpoint(name: str, c: Connector, response: Response, fresh: Fresh = False) -> EndpointInfo:
        return served(c, response, fresh, lambda: c.get_endpoint(name))

    # ---------------------------------------------------- independent dataset families
    # These aliases delegate to the SAME DatasetStore and connector as DBX-04. Legacy
    # model-scoped routes below remain available for Training Factory and older clients.

    @router.get("/mlops/datasets")
    @translate
    def dataset_catalog(
        c: Connector, response: Response, fresh: Fresh = False
    ) -> list[DatasetFamilySummary]:
        return served(c, response, fresh, lambda: dataset_store(c).catalog())

    @router.post("/mlops/datasets", status_code=201)
    @translate
    def create_dataset_family(body: FamilyBody, c: Connector) -> dict[str, Any]:
        return dataset_store(c).create_family(
            body.dataset_id,
            body.name,
            body.use_case,
            body.classes,
            body.synthetic,
            body.description,
        )

    @router.get("/mlops/datasets/{dataset_id}")
    @translate
    def dataset_family(
        dataset_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> DatasetIndex:
        return served(c, response, fresh, lambda: dataset_store(c).family_index(dataset_id))

    @router.get("/mlops/datasets/{dataset_id}/versions")
    @translate
    def family_versions(
        dataset_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> list[DatasetVersionSummary]:
        return served(
            c, response, fresh, lambda: dataset_store(c).family_index(dataset_id).versions
        )

    @router.get("/mlops/datasets/{dataset_id}/versions/{version}")
    @translate
    def family_version(
        dataset_id: str, version: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> DatasetVersionSummary:
        store = dataset_store(c)
        return served(
            c, response, fresh, lambda: store.version(store.scope_id(dataset_id), version)
        )

    @router.get("/mlops/datasets/{dataset_id}/versions/{version}/items")
    @translate
    def family_items(
        dataset_id: str,
        version: str,
        c: Connector,
        split: str | None = None,
        label: str | None = None,
        review: str | None = None,
        q: str | None = Query(None, max_length=100),
        offset: int = Query(0, ge=0),
        limit: int = Query(24, ge=1, le=48),
    ) -> ItemPage:
        store = dataset_store(c)
        return store.items(
            store.scope_id(dataset_id), version, split, label, review, q, offset, limit
        )

    @router.get("/mlops/datasets/{dataset_id}/versions/{version}/images/{file:path}")
    @translate
    def family_image(dataset_id: str, version: str, file: str, c: Connector) -> Response:
        store = dataset_store(c)
        data, media = store.image(store.scope_id(dataset_id), version, file)
        return Response(data, media_type=media, headers=IMMUTABLE_IMAGE)

    @router.post("/mlops/datasets/{dataset_id}/drafts", status_code=201)
    @translate
    def create_family_draft(dataset_id: str, body: FamilyDraftBody, c: Connector) -> dict[str, Any]:
        store = dataset_store(c)
        return store.create_draft(store.scope_id(dataset_id), body.parent_version)

    @router.get("/mlops/datasets/{dataset_id}/drafts/{draft_id}")
    @translate
    def family_draft(dataset_id: str, draft_id: str, c: Connector) -> dict[str, Any]:
        store = dataset_store(c)
        return store.get_draft(store.scope_id(dataset_id), draft_id)

    @router.delete("/mlops/datasets/{dataset_id}/drafts/{draft_id}", status_code=204)
    @translate
    def delete_family_draft(dataset_id: str, draft_id: str, c: Connector) -> None:
        store = dataset_store(c)
        store.delete_draft(store.scope_id(dataset_id), draft_id)

    @router.patch("/mlops/datasets/{dataset_id}/drafts/{draft_id}/items")
    @translate
    def change_family_items(
        dataset_id: str, draft_id: str, body: ItemChanges, c: Connector
    ) -> dict[str, Any]:
        store = dataset_store(c)
        return store.update_items(
            store.scope_id(dataset_id), draft_id, [change.model_dump() for change in body.changes]
        )

    @router.post("/mlops/datasets/{dataset_id}/drafts/{draft_id}/import")
    @translate
    def import_family_items(
        dataset_id: str,
        draft_id: str,
        c: Connector,
        files: Annotated[list[UploadFile], File()],
        label: Annotated[str, Form()],
        split: Annotated[str, Form()],
        synthetic_attested: Annotated[bool, Form()] = False,
        group: Annotated[str | None, Form()] = None,
    ) -> list[ImportResult]:
        store = dataset_store(c)
        stream = ((f.filename or "image", f.file) for f in files)
        return store.import_files(
            store.scope_id(dataset_id), draft_id, stream, label, split, synthetic_attested, group
        )

    @router.delete("/mlops/datasets/{dataset_id}/drafts/{draft_id}/imports/{sha}")
    @translate
    def remove_family_import(
        dataset_id: str, draft_id: str, sha: str, c: Connector
    ) -> dict[str, Any]:
        store = dataset_store(c)
        return store.remove_import(store.scope_id(dataset_id), draft_id, sha)

    @router.get("/mlops/datasets/{dataset_id}/drafts/{draft_id}/images/{sha}")
    @translate
    def family_draft_image(dataset_id: str, draft_id: str, sha: str, c: Connector) -> Response:
        store = dataset_store(c)
        data, media = store.draft_image(store.scope_id(dataset_id), draft_id, sha)
        return Response(data, media_type=media, headers=IMMUTABLE_IMAGE)

    @router.post("/mlops/datasets/{dataset_id}/drafts/{draft_id}/publish", status_code=202)
    @translate
    def publish_family_draft(
        dataset_id: str, draft_id: str, body: PublishBody, c: Connector
    ) -> PublishJob:
        store = dataset_store(c)
        return store.start_publish(store.scope_id(dataset_id), draft_id, body.version).model_copy()

    # ------------------------------------------------------------------ datasets (DBX-04)
    # Files API + Unity Catalog metadata only (no SQL warehouse). Published versions are
    # immutable folders; drafts are separate; a publication never triggers a training.

    @router.get("/mlops/models/{model_id}/datasets")
    @translate
    def datasets(
        model_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> DatasetIndex:
        return served(c, response, fresh, lambda: dataset_store(c).index(model_id))

    @router.get("/mlops/models/{model_id}/datasets/{version}")
    @translate
    def dataset_version(
        model_id: str, version: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> DatasetVersionSummary:
        return served(c, response, fresh, lambda: dataset_store(c).version(model_id, version))

    @router.get("/mlops/models/{model_id}/datasets/{version}/items")
    @translate
    def dataset_items(
        model_id: str,
        version: str,
        c: Connector,
        split: str | None = None,
        label: str | None = None,
        review: str | None = None,
        q: str | None = Query(None, max_length=100),
        offset: int = Query(0, ge=0),
        limit: int = Query(24, ge=1, le=48),
    ) -> ItemPage:
        return dataset_store(c).items(model_id, version, split, label, review, q, offset, limit)

    @router.get("/mlops/models/{model_id}/datasets/{version}/images/{file:path}")
    @translate
    def dataset_image(model_id: str, version: str, file: str, c: Connector) -> Response:
        data, media = dataset_store(c).image(model_id, version, file)
        return Response(data, media_type=media, headers=IMMUTABLE_IMAGE)

    @router.get("/mlops/models/{model_id}/dataset-tables")
    @translate
    def dataset_tables(
        model_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> list[TableInfo]:
        return served(c, response, fresh, lambda: dataset_store(c).tables(model_id))

    @router.get("/mlops/models/{model_id}/training-dataset")
    @translate
    def training_dataset(
        model_id: str, c: Connector, response: Response, fresh: Fresh = False
    ) -> TrainingDataset:
        return served(c, response, fresh, lambda: dataset_store(c).training_dataset(model_id))

    @router.post("/mlops/models/{model_id}/dataset-drafts", status_code=201)
    @translate
    def create_draft(model_id: str, body: DraftBody, c: Connector) -> dict[str, Any]:
        return dataset_store(c).create_draft(model_id, body.parent_version)

    @router.get("/mlops/models/{model_id}/dataset-drafts/{draft_id}")
    @translate
    def get_draft(model_id: str, draft_id: str, c: Connector) -> dict[str, Any]:
        return dataset_store(c).get_draft(model_id, draft_id)

    @router.delete("/mlops/models/{model_id}/dataset-drafts/{draft_id}", status_code=204)
    @translate
    def delete_draft(model_id: str, draft_id: str, c: Connector) -> None:
        dataset_store(c).delete_draft(model_id, draft_id)

    @router.patch("/mlops/models/{model_id}/dataset-drafts/{draft_id}/items")
    @translate
    def update_draft_items(
        model_id: str, draft_id: str, body: ItemChanges, c: Connector
    ) -> dict[str, Any]:
        changes = [ch.model_dump() for ch in body.changes]
        return dataset_store(c).update_items(model_id, draft_id, changes)

    @router.post("/mlops/models/{model_id}/dataset-drafts/{draft_id}/import")
    @translate
    def import_into_draft(
        model_id: str,
        draft_id: str,
        c: Connector,
        files: Annotated[list[UploadFile], File()],
        label: Annotated[str, Form()],
        split: Annotated[str, Form()],
        synthetic_attested: Annotated[bool, Form()] = False,
        group: Annotated[str | None, Form()] = None,
    ) -> list[ImportResult]:
        stream = ((f.filename or "image", f.file) for f in files)
        return dataset_store(c).import_files(
            model_id, draft_id, stream, label, split, synthetic_attested, group
        )

    @router.delete("/mlops/models/{model_id}/dataset-drafts/{draft_id}/imports/{sha}")
    @translate
    def remove_import(model_id: str, draft_id: str, sha: str, c: Connector) -> dict[str, Any]:
        return dataset_store(c).remove_import(model_id, draft_id, sha)

    @router.get("/mlops/models/{model_id}/dataset-drafts/{draft_id}/images/{sha}")
    @translate
    def draft_image(model_id: str, draft_id: str, sha: str, c: Connector) -> Response:
        data, media = dataset_store(c).draft_image(model_id, draft_id, sha)
        return Response(data, media_type=media, headers=IMMUTABLE_IMAGE)

    @router.post("/mlops/models/{model_id}/dataset-drafts/{draft_id}/publish", status_code=202)
    @translate
    def publish_draft(model_id: str, draft_id: str, body: PublishBody, c: Connector) -> PublishJob:
        """Starts the publication in the background; follow it with /mlops/dataset-jobs/{id}.
        Never triggers a training job."""
        return dataset_store(c).start_publish(model_id, draft_id, body.version).model_copy()

    @router.get("/mlops/dataset-jobs/{job_id}")
    @translate
    def dataset_job(job_id: str, c: Connector) -> PublishJob:
        return dataset_store(c).job(job_id).model_copy()

    # DBX-05 Training Factory (dedicated module, same connector and cache).
    router.include_router(create_training_router(get_connector))
    # DBX-07B Monitoring (dedicated module; local history only, GET never writes).
    router.include_router(create_monitoring_router(get_connector, get_policy=_POLICIES.get))
    # DBX-08 retraining policies (single launch path: TrainingService.launch).
    router.include_router(create_retraining_router(get_connector))

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
            snap = monitoring.last_snapshot
            if snap and snap.metrics and any(d.alert for d in snap.metrics.drift):
                alerts = ", ".join(
                    f"{d.feature} PSI {d.value:.2f}" for d in snap.metrics.drift if d.alert
                )
                drifts.append(
                    {
                        "modelId": managed.id,
                        "title": managed.display_name,
                        "detail": "Dernier résultat connu "
                        f"(lu le {snap.read_at:%d/%m/%Y %H:%M} UTC) : "
                        f"dérive des données {alerts} (seuil 0,2)",
                        "healthPct": health,
                        "mode": _policy_mode(),
                        "stale": True,
                    }
                )
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
