"""Configuration of the ARGOS Databricks integration (environment + managed model list).

Nothing else in the code names a Databricks resource: change a resource here (or in the
JSON file given by ``ARGOS_DBX_MODELS_FILE``), never in the services.

| Variable                       | Default                                          |
|--------------------------------|--------------------------------------------------|
| ``DATABRICKS_CONFIG_PROFILE``  | ``ARGOS`` (CLI OAuth profile; no token handled)  |
| ``ARGOS_DBX_MODELS_FILE``      | none -> the DBX-00 POC model below               |
| ``ARGOS_DBX_EXPERIMENTS``      | ``/Shared/ARGOS-POC/quality-demo`` (comma list)   |
| ``ARGOS_DBX_CATALOG``          | ``workspace``                                    |
| ``ARGOS_DBX_MONITORING_TABLE`` | ``workspace.argos_poc.drift_report``             |
| ``ARGOS_DBX_WAREHOUSE_ID``     | first warehouse of the workspace                 |
| ``ARGOS_DBX_WAREHOUSE_AUTOSTART`` | ``false``: monitoring never starts a warehouse |
| ``ARGOS_DBX_CACHE_SECONDS``    | ``300`` (monitoring cache, avoids SQL polling)   |
| ``ARGOS_DBX_SNAPSHOT_DIR``     | ``<ARGOS_MLOPS_HOME>/dbx_cache`` (last good read) |
| ``ARGOS_DBX_INFERENCE_TIMEOUT``| ``30`` seconds                                   |
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field


class ManagedModel(BaseModel):
    """A model ARGOS manages. ``id`` is the stable id used by the frontend."""

    id: str
    display_name: str
    use_case: str = Field(description="Qualité | EPI | Comportement | Poste (frontend labels)")
    argos_use_case: str = Field(description="quality | safety | workstation (ARGOS contracts)")
    scope: str
    uc_name: str = Field(description="Unity Catalog model catalog.schema.model")
    endpoint: str | None = Field(default=None, description="Serving endpoint, if served")
    training_job: str | None = Field(default=None, description="Existing Lakeflow job name")
    synthetic: bool = False
    # DBX-04: where the model's dataset versions live (Unity Catalog Volume folder, one
    # immutable sub-folder per version with its manifest.json) and their Delta mirrors.
    dataset_root: str | None = Field(default=None, description="/Volumes/<cat>/<schema>/<vol>")
    dataset_name: str | None = None
    dataset_tables: list[str] = Field(default_factory=list)


DEFAULT_MODELS = [
    ManagedModel(
        id="quality-poc",
        display_name="Qualité (POC synthétique DBX-00)",
        use_case="Qualité",
        argos_use_case="quality",
        scope="Démonstration — données synthétiques",
        uc_name="workspace.argos_poc.quality_demo",
        endpoint="argos-quality-poc",
        training_job="argos-poc-quality-training",
        synthetic=True,
        dataset_root="/Volumes/workspace/argos_poc/images",
        dataset_name="quality-synthetic",
        dataset_tables=["workspace.argos_poc.annotations", "workspace.argos_poc.dataset_versions"],
    ),
    # DBX-05D-FIX: the Quality group's YOLO model (candidates only; not served, no dataset
    # root: its datasets live in the independent catalogue).
    ManagedModel(
        id="quality-industrial",
        display_name="Qualité 702 — YOLO26n-cls (groupe Quality)",
        use_case="Qualité",
        argos_use_case="quality",
        scope="Candidats entraînés par Training Factory (données synthétiques pour l'instant)",
        uc_name="workspace.argos_poc.quality_industrial",
        endpoint=None,
        training_job="hovis-quality-industrial-training",
        synthetic=True,
    ),
    # SCI-02: binary OK / NOK model of the same kit, trained on the industrial 702 folds. A
    # SEPARATE registered model: never compared with nor promoted over the 3-class model.
    ManagedModel(
        id="quality-industrial-binary",
        display_name="Qualité 702 binaire — YOLO26n-cls (groupe Quality)",
        use_case="Qualité",
        argos_use_case="quality",
        scope="Candidats OK / NOK entraînés par Training Factory sur les plis industriels 702",
        uc_name="workspace.argos_poc.quality_industrial_binary",
        endpoint=None,
        training_job="hovis-quality-industrial-binary-training",
        synthetic=False,
    ),
]


def _mlops_home() -> Path:
    return Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DatabricksSettings:
    profile: str = "ARGOS"
    catalog: str = "workspace"
    experiments: tuple[str, ...] = ("/Shared/ARGOS-POC/quality-demo",)
    monitoring_table: str = "workspace.argos_poc.drift_report"
    warehouse_id: str | None = None
    warehouse_autostart: bool = False
    cache_seconds: int = 300
    # DBX-PERF-01: read cache, timeouts and per-request time budget (all bounded).
    read_ttl_seconds: int = 60
    finished_run_ttl_seconds: int = 3600
    http_timeout_seconds: int = 15
    retry_timeout_seconds: int = 30
    request_budget_seconds: int = 25
    snapshot_dir: str = field(default_factory=lambda: str(_mlops_home() / "dbx_cache"))
    inference_timeout_s: int = 30
    models: tuple[ManagedModel, ...] = field(default_factory=lambda: tuple(DEFAULT_MODELS))
    # Independent families live below the existing UC Volume, apart from legacy versions.
    dataset_catalog_root: str | None = None
    # Jobs that may be triggered through the API besides the models' training jobs.
    extra_triggerable_jobs: tuple[str, ...] = ("argos-poc-drift-monitor",)

    @property
    def triggerable_jobs(self) -> set[str]:
        return {m.training_job for m in self.models if m.training_job} | set(
            self.extra_triggerable_jobs
        )

    @classmethod
    def from_env(cls) -> DatabricksSettings:
        env = os.environ
        models = DEFAULT_MODELS
        if env.get("ARGOS_DBX_MODELS_FILE"):
            raw = json.loads(Path(env["ARGOS_DBX_MODELS_FILE"]).read_text(encoding="utf-8"))
            models = [ManagedModel.model_validate(m) for m in raw]
        experiments = env.get("ARGOS_DBX_EXPERIMENTS", "/Shared/ARGOS-POC/quality-demo")
        return cls(
            profile=env.get("DATABRICKS_CONFIG_PROFILE", "ARGOS"),
            catalog=env.get("ARGOS_DBX_CATALOG", "workspace"),
            experiments=tuple(e.strip() for e in experiments.split(",") if e.strip()),
            monitoring_table=env.get(
                "ARGOS_DBX_MONITORING_TABLE", "workspace.argos_poc.drift_report"
            ),
            warehouse_id=env.get("ARGOS_DBX_WAREHOUSE_ID") or None,
            warehouse_autostart=_truthy(env.get("ARGOS_DBX_WAREHOUSE_AUTOSTART")),
            cache_seconds=int(env.get("ARGOS_DBX_CACHE_SECONDS", 300)),
            read_ttl_seconds=int(env.get("ARGOS_DBX_READ_TTL", 60)),
            request_budget_seconds=int(env.get("ARGOS_DBX_REQUEST_BUDGET", 25)),
            snapshot_dir=env.get("ARGOS_DBX_SNAPSHOT_DIR", str(_mlops_home() / "dbx_cache")),
            inference_timeout_s=int(env.get("ARGOS_DBX_INFERENCE_TIMEOUT", 30)),
            models=tuple(models),
            dataset_catalog_root=env.get("ARGOS_DBX_DATASET_CATALOG_ROOT") or None,
            extra_triggerable_jobs=tuple(
                j.strip()
                for j in env.get("ARGOS_DBX_TRIGGERABLE_JOBS", "argos-poc-drift-monitor").split(",")
                if j.strip()
            ),
        )

    def model(self, model_id: str) -> ManagedModel | None:
        return next((m for m in self.models if m.id == model_id), None)

    def apply_process_environment(self) -> None:
        """MLflow on Databricks for THIS process only (never the Windows environment)."""
        os.environ["DATABRICKS_CONFIG_PROFILE"] = self.profile
        os.environ["MLFLOW_TRACKING_URI"] = "databricks"
        os.environ["MLFLOW_REGISTRY_URI"] = "databricks-uc"
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        # MLflow defaults are 120 s per request and up to 500 s of retries: bound them.
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", str(self.http_timeout_seconds))
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
        os.environ.setdefault(
            "MLFLOW_DATABRICKS_ENDPOINT_HTTP_RETRY_TIMEOUT", str(self.retry_timeout_seconds)
        )
        ensure_cli_on_path()


def ensure_cli_on_path() -> None:
    """The ARGOS profile uses auth_type=databricks-cli: the SDK calls the CLI for tokens.
    WinGet installs it outside some shells' PATH: append it for this process only."""
    if shutil.which("databricks"):
        return
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for exe in sorted(packages.glob("Databricks.DatabricksCLI_*/databricks.exe")):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(exe.parent)
        return
