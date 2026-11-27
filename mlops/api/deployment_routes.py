"""Explicit model decisions and guarded Databricks Serving lifecycle routes."""

import functools
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from mlops.databricks.connector import DatabricksConnectorError
from mlops.deployment.contracts import (
    DecisionRecord,
    DecisionRequest,
    DeploymentConfirmRequest,
    DeploymentOperation,
    DeploymentPrepareRequest,
    LifecycleError,
    RollbackPrepareRequest,
)
from mlops.deployment.runtime import lifecycle_service
from mlops.deployment.service import LifecycleService


def lifecycle_http(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (LifecycleError, DatabricksConnectorError) as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    return wrapper


def create_deployment_router(
    get_service: Callable[[], LifecycleService] | None = None,
) -> APIRouter:
    if get_service is None:
        # Imported here so the existing router can include this one without a circular import.
        from mlops.api.routes import default_connector

        def get_service() -> LifecycleService:
            return lifecycle_service(default_connector())

    router = APIRouter(tags=["model lifecycle"])
    Service = Annotated[LifecycleService, Depends(get_service)]

    @router.get("/mlops/deployments", response_model=list[DeploymentOperation])
    @lifecycle_http
    def operations(
        service: Service, endpoint: str | None = None, limit: int = Query(100, ge=1, le=500)
    ):
        return service.store.list(endpoint, limit)

    @router.post("/mlops/deployments/prepare", status_code=201, response_model=DeploymentOperation)
    @lifecycle_http
    def prepare(body: DeploymentPrepareRequest, service: Service):
        return service.prepare(body)

    @router.post(
        "/mlops/deployments/rollback/prepare", status_code=201, response_model=DeploymentOperation
    )
    @lifecycle_http
    def prepare_rollback(body: RollbackPrepareRequest, service: Service):
        return service.prepare_rollback(body)

    @router.get("/mlops/deployments/{operation_id}", response_model=DeploymentOperation)
    @lifecycle_http
    def operation(operation_id: str, service: Service):
        return service.reconcile(operation_id)

    @router.get("/mlops/deployments/{operation_id}/events")
    @lifecycle_http
    def operation_events(operation_id: str, service: Service) -> list[dict]:
        return service.store.events(operation_id)

    @router.post(
        "/mlops/deployments/{operation_id}/confirm",
        status_code=202,
        response_model=DeploymentOperation,
    )
    @lifecycle_http
    def confirm(operation_id: str, body: DeploymentConfirmRequest, service: Service):
        return service.confirm(operation_id, body.confirmation)

    @router.post(
        "/mlops/registry/{model_id}/versions/{version}/decisions", response_model=DecisionRecord
    )
    @lifecycle_http
    def decide(model_id: str, version: str, body: DecisionRequest, service: Service):
        return service.decide(model_id, version, body)

    @router.get("/mlops/registry/{model_id}/versions/{version}/decision-state")
    @lifecycle_http
    def decision_state(model_id: str, version: str, service: Service) -> dict:
        return service.decision_state(model_id, version)

    @router.get(
        "/mlops/registry/{model_id}/versions/{version}/decisions",
        response_model=list[DecisionRecord],
    )
    @lifecycle_http
    def decisions(model_id: str, version: str, service: Service):
        return service.store.decisions(model_id, version)

    return router
