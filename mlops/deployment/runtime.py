"""Process-local wiring for the durable lifecycle service."""

from __future__ import annotations

import threading

from mlops.databricks.connector import DatabricksConnector
from mlops.deployment.gateway import DatabricksDeploymentGateway
from mlops.deployment.service import LifecycleService
from mlops.deployment.store import OperationStore

_store: OperationStore | None = None
_lock = threading.Lock()


def operation_store() -> OperationStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = OperationStore()
    return _store


def lifecycle_service(connector: DatabricksConnector) -> LifecycleService:
    targets = {model.id: model.endpoint for model in connector.settings.models}
    return LifecycleService(DatabricksDeploymentGateway(connector), operation_store(), targets)
