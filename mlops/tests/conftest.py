"""MLOps tests run in the ARGOS MLOps environment (MLflow installed), from the repo root:

    <ARGOS_MLOPS_HOME>\\.venv\\Scripts\\python.exe -m pytest mlops/tests              # unit only
    $env:ARGOS_MLFLOW_IT = "1"; ...python.exe -m pytest mlops/tests     # + real server

They are NOT collected by the historical ARGOS CI (testpaths = tests, usecases).
"""

import os

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "mlflow_server: needs a running MLflow server (set ARGOS_MLFLOW_IT=1)"
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ARGOS_MLFLOW_IT") == "1":
        return
    skip = pytest.mark.skip(reason="real MLflow server tests: set ARGOS_MLFLOW_IT=1 to run them")
    for item in items:
        if "mlflow_server" in item.keywords:
            item.add_marker(skip)
