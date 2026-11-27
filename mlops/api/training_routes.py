"""DBX-05 Training Factory routes (``/api/mlops/training/...``), included by the MLOps router.

Reads use the request scope of DBX-PERF-01 (cache, freshness headers, time budget). Remote
writes (launch, cancel) are refused while ``HOVIS_TRAINING_REMOTE`` is not ``1``.
"""

import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from mlops.databricks.connector import DatabricksConnector, DatabricksConnectorError
from mlops.databricks.datasets import InvalidDatasetRequest
from mlops.databricks.read_cache import BudgetExceeded, read_scope
from mlops.training.checks import DatasetPreview
from mlops.training.service import (
    Kpis,
    LaunchRecord,
    TrainingRow,
    TrainingService,
    ValidationReport,
)
from mlops.training.specs import PipelineView

_LOCK = threading.Lock()
SAFE_ARTIFACT = (".json", ".csv", ".md", ".yaml", ".yml", ".txt", ".png", ".onnx", ".pt")
MAX_ARTIFACT_BYTES = 60 * 1024 * 1024


def service_for(c: DatabricksConnector) -> TrainingService:
    svc = getattr(c, "_training_service", None)
    if svc is None:
        with _LOCK:
            svc = getattr(c, "_training_service", None)
            if svc is None:
                svc = TrainingService(c)
                c._training_service = svc
    return svc


class LaunchBody(BaseModel):
    pipeline_id: str
    dataset_id: str
    version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


def create_training_router(get_connector: Callable[[], DatabricksConnector]) -> APIRouter:
    router = APIRouter(prefix="/mlops/training", tags=["training"])
    Connector = Annotated[DatabricksConnector, Depends(get_connector)]

    def call(
        c: DatabricksConnector, response: Response | None, fresh: bool, fn: Callable[[], Any]
    ) -> Any:
        try:
            with read_scope(fresh=fresh, budget=c.settings.request_budget_seconds) as scope:
                result = fn()
            if response is not None:
                response.headers.update(scope.headers())
            return result
        except InvalidDatasetRequest as exc:
            raise HTTPException(400, str(exc)) from exc
        except DatabricksConnectorError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(503, f"Databricks too slow: {exc}") from exc

    @router.get("/pipelines")
    def pipelines(c: Connector, response: Response, fresh: bool = False) -> list[PipelineView]:
        return call(c, response, fresh, lambda: service_for(c).pipelines())

    @router.get("/pipelines/{pipeline_id}/datasets")
    def datasets(
        pipeline_id: str, c: Connector, response: Response, fresh: bool = False
    ) -> list[dict[str, Any]]:
        return call(c, response, fresh, lambda: service_for(c).compatible_datasets(pipeline_id))

    @router.get("/datasets/{dataset_id}/versions/{version}/preview")
    def preview(dataset_id: str, version: str, c: Connector, response: Response) -> DatasetPreview:
        return call(
            c, response, False, lambda: service_for(c).resolver.preview(dataset_id, version)
        )

    @router.post("/validate")
    def validate(body: LaunchBody, c: Connector) -> ValidationReport:
        return call(
            c,
            None,
            False,
            lambda: service_for(c).validate(
                body.pipeline_id, body.dataset_id, body.version, body.parameters
            ),
        )

    @router.post("/launch", status_code=202)
    def launch(body: LaunchBody, c: Connector) -> LaunchRecord:
        """Never launches twice for one idempotency key (double click, doubtful answer)."""
        return call(
            c,
            None,
            False,
            lambda: service_for(c).launch(
                body.pipeline_id,
                body.dataset_id,
                body.version,
                body.parameters,
                body.idempotency_key or "",
            ),
        )

    @router.get("/summary")
    def summary(c: Connector, response: Response, fresh: bool = False) -> Kpis:
        return call(c, response, fresh, lambda: service_for(c).kpis())

    @router.get("/runs")
    def runs(c: Connector, response: Response, fresh: bool = False) -> list[TrainingRow]:
        return call(c, response, fresh, lambda: service_for(c).trainings())

    @router.get("/runs/{job_run_id}")
    def detail(job_run_id: int, c: Connector, response: Response) -> dict[str, Any]:
        return call(c, response, False, lambda: service_for(c).detail(job_run_id))

    @router.post("/runs/{job_run_id}/cancel", status_code=202)
    def cancel(job_run_id: int, c: Connector) -> dict[str, str]:
        call(c, None, False, lambda: service_for(c).cancel(job_run_id))
        return {"status": "cancellation requested"}

    @router.get("/runs/{job_run_id}/logs")
    def logs(job_run_id: int, c: Connector) -> dict[str, Any]:
        return call(c, None, False, lambda: service_for(c).logs(job_run_id))

    @router.get("/mlflow-runs/{run_id}/history")
    def history(run_id: str, c: Connector, response: Response) -> dict[str, Any]:
        return call(c, response, False, lambda: service_for(c).history(run_id))

    @router.get("/mlflow-runs/{run_id}/evaluation")
    def evaluation(run_id: str, c: Connector) -> dict[str, Any]:
        return call(c, None, False, lambda: service_for(c).evaluation(run_id))

    @router.get("/mlflow-runs/{run_id}/predictions")
    def predictions(
        run_id: str,
        c: Connector,
        dataset_id: str | None = None,
        version: str | None = None,
        true: str | None = None,
        pred: str | None = None,
        kind: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(24, ge=1, le=48),
    ) -> dict[str, Any]:
        filters = {k: v for k, v in {"true": true, "pred": pred, "kind": kind}.items() if v}
        return call(
            c,
            None,
            False,
            lambda: service_for(c).predictions(run_id, dataset_id, version, filters, offset, limit),
        )

    @router.get("/mlflow-runs/{run_id}/artifacts")
    def artifacts(run_id: str, c: Connector) -> list[dict[str, Any]]:
        return call(c, None, False, lambda: service_for(c).artifacts(run_id))

    @router.get("/mlflow-runs/{run_id}/artifact")
    def artifact(run_id: str, c: Connector, path: str = Query(..., max_length=300)) -> Response:
        if ".." in path or path.startswith("/") or not path.lower().endswith(SAFE_ARTIFACT):
            raise HTTPException(400, "artifact path refused")
        data = call(c, None, False, lambda: service_for(c)._artifact(run_id, path))
        if data is None:
            raise HTTPException(404, "artifact not found")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise HTTPException(413, "artifact too large")
        name = path.rsplit("/", 1)[-1]
        inline = name.endswith((".json", ".csv", ".md", ".yaml", ".yml", ".txt", ".png"))
        media = (
            "image/png"
            if name.endswith(".png")
            else "text/plain; charset=utf-8"
            if inline
            else "application/octet-stream"
        )
        disposition = "inline" if inline else f'attachment; filename="{name}"'
        return Response(data, media_type=media, headers={"Content-Disposition": disposition})

    return router
