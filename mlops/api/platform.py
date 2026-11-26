"""Local ARGOS backend gateway: the Core app (unchanged) + the MLOps router, one process.

    $env:ARGOS_CORE_DB = "var/argos-integration-core.sqlite3"
    python -m uvicorn mlops.api.platform:app --host 127.0.0.1 --port 8020   # MLOps venv python

Core routes (``/health``, ``/ingest/v1/events``, ``/api/v1/*``) and MLOps routes
(``/api/models/*``, ``/api/mlops/*``) do not overlap; ``route_collisions`` checks it.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from mlops.api.routes import create_mlops_router
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
    return application


app = create_platform_app()
