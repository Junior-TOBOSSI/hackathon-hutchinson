"""Shared names, clients and safety guards of the DBX-00 proof of concept.

Every Databricks resource of the POC is named here, so that it can be found and deleted
precisely (see README.md, "Cleanup"). Authentication always goes through the existing
Databricks CLI profile (OAuth); no token is ever read, printed or stored by this code.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "ARGOS")

CATALOG = "workspace"
SCHEMA = "argos_poc"
VOLUME = "images"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
DATASET_VERSION = "synthetic-v1"
DATASET_DIR = f"{VOLUME_PATH}/{DATASET_VERSION}"

TABLE_ANNOTATIONS = f"{CATALOG}.{SCHEMA}.annotations"
TABLE_DATASET_VERSIONS = f"{CATALOG}.{SCHEMA}.dataset_versions"
TABLE_TELEMETRY = f"{CATALOG}.{SCHEMA}.telemetry"
TABLE_DRIFT = f"{CATALOG}.{SCHEMA}.drift_report"

WORKSPACE_DIR = "/Shared/ARGOS-POC"
EXPERIMENT = f"{WORKSPACE_DIR}/quality-demo"
JOB_NAME = "argos-poc-quality-training"
MONITOR_JOB_NAME = "argos-poc-drift-monitor"
MODEL = f"{CATALOG}.{SCHEMA}.quality_demo"
ENDPOINT = "argos-quality-poc"

MAX_REMOTE_INFERENCES = 20

LOCAL_HOME = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL")) / "dbx_poc"
LOCAL_DATASET = LOCAL_HOME / "dataset" / DATASET_VERSION
RESULTS = LOCAL_HOME / "results"
BUDGET_FILE = LOCAL_HOME / "inference_budget.json"


def setup_environment() -> None:
    """Configure THIS process only (never the Windows environment)."""
    os.environ["DATABRICKS_CONFIG_PROFILE"] = PROFILE
    os.environ["MLFLOW_TRACKING_URI"] = "databricks"
    os.environ["MLFLOW_REGISTRY_URI"] = "databricks-uc"
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    _ensure_cli_on_path()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _ensure_cli_on_path() -> None:
    """The ARGOS profile uses auth_type=databricks-cli: the SDK calls the CLI to get tokens.

    WinGet installs the CLI outside the PATH of some shells: append its folder to the PATH
    of this process only (existing entries, including the active venv, are kept first).
    """
    if shutil.which("databricks"):
        return
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for exe in sorted(packages.glob("Databricks.DatabricksCLI_*/databricks.exe")):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(exe.parent)
        return


def workspace_client():
    from databricks.sdk import WorkspaceClient

    setup_environment()
    return WorkspaceClient(profile=PROFILE)


def save_result(name: str, data: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{name}.json"
    payload = {"recorded_at": datetime.now(UTC).isoformat(), **data}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def consume_inference_budget(count: int, purpose: str) -> int:
    """Refuse any remote inference beyond MAX_REMOTE_INFERENCES for the whole POC."""
    LOCAL_HOME.mkdir(parents=True, exist_ok=True)
    state = json.loads(BUDGET_FILE.read_text(encoding="utf-8")) if BUDGET_FILE.exists() else {}
    used = state.get("used", 0)
    if used + count > MAX_REMOTE_INFERENCES:
        raise RuntimeError(
            f"inference budget exceeded: {used} used, {count} requested, "
            f"max {MAX_REMOTE_INFERENCES}"
        )
    state["used"] = used + count
    state.setdefault("log", []).append(
        {"at": datetime.now(UTC).isoformat(), "count": count, "purpose": purpose}
    )
    BUDGET_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state["used"]


def remaining_inferences() -> int:
    if not BUDGET_FILE.exists():
        return MAX_REMOTE_INFERENCES
    return MAX_REMOTE_INFERENCES - json.loads(BUDGET_FILE.read_text(encoding="utf-8"))["used"]
