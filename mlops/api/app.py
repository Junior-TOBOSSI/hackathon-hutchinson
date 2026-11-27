"""Standalone ARGOS MLOps API (until the router is included in the Core).

    python -m uvicorn mlops.api.app:app --host 127.0.0.1 --port 8040   # MLOps venv python

All routes are under ``/api`` like argos-ui expects (its Vite proxy forwards ``/api``).
"""

from __future__ import annotations

from fastapi import FastAPI

from mlops.api.deployment_routes import create_deployment_router
from mlops.api.routes import create_mlops_router

app = FastAPI(title="ARGOS MLOps API (Databricks)", version="0.1.0")
app.include_router(create_mlops_router(), prefix="/api")
app.include_router(create_deployment_router(), prefix="/api")
