"""Local ARGOS backend gateway: the Core app (unchanged) + the MLOps router, one process.

    $env:ARGOS_CORE_DB = "var/argos-integration-core.sqlite3"
    python -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8020   # MLOps venv python

Warm-up (DBX-PERF-01): with ``HOVIS_MLOPS_WARMUP=1`` a background thread builds the
Databricks clients and reads the registry / serving / jobs state once (control-plane reads
only: no SQL warehouse, no job, no inference). It never blocks the startup and its errors
are only logged; the first browser request then finds warm clients and a filled cache.

Core routes (``/health``, ``/ingest/v1/events``, ``/api/v1/*``) and MLOps routes
(``/api/models/*``, ``/api/mlops/*``) do not overlap; ``route_collisions`` checks it.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import APIRouter, FastAPI

from mlops.api.deployment_routes import create_deployment_router
from mlops.api.routes import build_overview, create_mlops_router, default_connector
from mlops.databricks.datasets import dataset_store
from mlops.databricks.read_cache import read_scope
from visionhub.core.app import create_app

PREFIX = "/api"


def _keys(routes, prefix: str = "") -> set[tuple[str, str]]:
    # FastAPI >= 0.16x lists included routers as lazy objects without .path: skip them.
    return {
        (method, prefix + route.path)
        for route in routes
        if hasattr(route, "path")
        for method in (getattr(route, "methods", None) or ())
    }


def route_collisions(core: FastAPI, router: APIRouter, prefix: str) -> list[str]:
    return sorted(f"{m} {p}" for m, p in _keys(core.routes) & _keys(router.routes, prefix))


def create_platform_app() -> FastAPI:
    application = create_app()
    router = create_mlops_router()
    collisions = route_collisions(application, router, PREFIX)
    if collisions:
        raise RuntimeError(f"route collisions between Core and MLOps: {collisions}")
    application.include_router(router, prefix=PREFIX)
    application.include_router(create_deployment_router(), prefix=PREFIX)
    return application


log = logging.getLogger("hovis.mlops.warmup")


def warm_up() -> None:
    """Fill the clients and the read cache; bounded, never raises."""
    started = time.perf_counter()
    try:
        connector = default_connector()
        with read_scope(budget=connector.settings.request_budget_seconds * 2):
            # Same reads as the Overview screen: registry + runs (overview), serving, jobs,
            # MLflow tracking (experiments). The monitoring part only reads the warehouse
            # STATE; it never starts it.
            build_overview(connector)
            connector.list_endpoints()
            connector.list_jobs()
            connector.list_experiments()
            # Dataset index (manifests only, never images) for the models that have one.
            for managed in connector.settings.models:
                if managed.dataset_root:
                    dataset_store(connector).index(managed.id)
        log.warning("MLOps warm-up done in %.1f s", time.perf_counter() - started)
    except Exception as exc:  # noqa: BLE001 - warm-up is best effort only
        log.warning("MLOps warm-up skipped: %s", type(exc).__name__)


def start_warm_up() -> threading.Thread:
    thread = threading.Thread(target=warm_up, name="hovis-mlops-warmup", daemon=True)
    thread.start()
    return thread


app = create_platform_app()
if os.environ.get("HOVIS_MLOPS_WARMUP") == "1":
    start_warm_up()
