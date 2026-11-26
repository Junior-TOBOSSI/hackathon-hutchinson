"""MLOps contracts (BUILD side) and the model package delivered to the Edge (RUN side).

MLflow is the source of truth for experiments, runs, registered models, versions and
aliases. ARGOS only keeps references to them (``ModelRef``) plus what MLflow does not
know: which station runs which version, deployment approvals and retraining policies.
These contracts work with a standalone MLflow server and with Databricks (Unity Catalog
names such as ``catalog.schema.model`` are accepted as ``registered_model``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from visionhub.contracts import Contract, Thresholds, UseCase
from visionhub.production.contracts import StationId

SHA256 = r"^[0-9a-f]{64}$"


class DatasetRef(Contract):
    """A versioned dataset (DVC tag/commit or manifest hash). Never the data itself."""

    name: str
    version: str = Field(description="DVC tag/commit, or sha256 of the manifest")
    uri: str = Field(description="DVC remote path or storage URI (no public URL)")
    manifest_sha256: str | None = Field(default=None, pattern=SHA256)
    num_samples: int = Field(ge=0)
    splits: dict[str, int] = Field(default_factory=dict, description="split -> samples")
    split_strategy: Literal["by_sequence", "by_time", "by_station", "random"]
    confidential: bool = True
    classes: list[str] = Field(default_factory=list)


class TrainingConfig(Contract):
    use_case: UseCase
    task: Literal["classification", "detection", "segmentation", "pose", "anomaly"]
    architecture: str = Field(description="e.g. yolo26n-cls, yoloe-s, rf-detr-base")
    base_weights: str | None = None
    image_size: tuple[int, int] = Field(description="(width, height) fed to the model")
    epochs: int = Field(ge=1)
    batch_size: int = Field(ge=1)
    seed: int = 0
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    dataset: DatasetRef


class TrainingJob(Contract):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    trigger: Literal["manual", "policy", "schedule"]
    config: TrainingConfig
    mlflow_experiment_id: str | None = None
    mlflow_run_id: str | None = None
    compute: str | None = Field(default=None, description="e.g. a100-cluster, databricks-job")
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None


class EvaluationMetrics(Contract):
    """Evaluation of one run on one dataset split (logged in MLflow, mirrored here)."""

    mlflow_run_id: str
    dataset: DatasetRef
    split: str = "test"
    metrics: dict[str, float] = Field(description="e.g. recall_nok, false_reject_rate, map50")
    per_class: dict[str, dict[str, float]] = Field(default_factory=dict)
    confusion_matrix: list[list[int]] | None = None
    class_order: list[str] = Field(default_factory=list)
    recommended_thresholds: Thresholds | None = None
    latency_ms_p50_cpu: float | None = Field(default=None, ge=0)
    latency_ms_p95_cpu: float | None = Field(default=None, ge=0)


class ModelRef(Contract):
    """Pointer to an MLflow registered model version."""

    registered_model: str = Field(description="MLflow name, or catalog.schema.model (UC)")
    version: str = Field(pattern=r"^[0-9]+$", description="MLflow model version number")
    alias: str | None = Field(default=None, description="e.g. champion, challenger")
    mlflow_run_id: str | None = None

    @property
    def uri(self) -> str:
        return f"models:/{self.registered_model}/{self.version}"


class ArtifactRef(Contract):
    uri: str = Field(description="MLflow artifact URI or file path inside the package")
    sha256: str = Field(pattern=SHA256)
    size_bytes: int = Field(ge=0)
    format: Literal["onnx", "torchscript", "pt", "openvino", "other"]


class PreprocessingSpec(Contract):
    input_size: tuple[int, int] = Field(description="(width, height)")
    color: Literal["BGR", "RGB"] = "RGB"
    resize: Literal["letterbox", "stretch", "center_crop"] = "letterbox"
    normalize_mean: tuple[float, float, float] | None = None
    normalize_std: tuple[float, float, float] | None = None
    roi: tuple[int, int, int, int] | None = Field(default=None, description="x, y, w, h px")


class ModelPackage(Contract):
    """Everything an Edge needs to run a model, delivered by MLOps (``model-package.json``).

    The Edge loads ``analyzer_class`` with ``params`` (merged with ``artifact`` path) and
    refuses the package if the artifact sha256 does not match.
    """

    package_schema: Literal["argos.model-package/1"] = "argos.model-package/1"
    use_case: UseCase
    model: ModelRef
    analyzer_class: str = Field(pattern=r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
    runtime: Literal["onnxruntime", "ultralytics", "torch", "opencv"]
    device: Literal["cpu", "cuda"] = "cpu"
    artifact: ArtifactRef
    preprocessing: PreprocessingSpec
    classes: list[str]
    thresholds: Thresholds
    params: dict[str, Any] = Field(default_factory=dict)
    dataset: DatasetRef
    evaluation: EvaluationMetrics | None = None
    created_at: datetime


class ModelDeployment(Contract):
    """Request to run a model version on a station. Always approved by a human first."""

    deployment_id: str
    station_id: StationId
    use_case: UseCase
    model: ModelRef
    package_sha256: str = Field(pattern=SHA256)
    status: Literal["pending_approval", "approved", "deploying", "active", "failed", "rolled_back"]
    requested_at: datetime
    approved_at: datetime | None = None
    approved_by_role: Literal["ai_leader"] | None = None
    previous_model: ModelRef | None = Field(default=None, description="Rollback target")

    @model_validator(mode="after")
    def _approval(self) -> ModelDeployment:
        if self.status in ("approved", "deploying", "active") and self.approved_at is None:
            raise ValueError(f"a deployment in status {self.status!r} must have been approved")
        return self


class StationDeploymentStatus(Contract):
    """What a station ACTUALLY runs (from the model.status edge events)."""

    station_id: StationId
    use_case: UseCase
    status: Literal["loaded", "loading", "failed", "absent"]
    model: ModelRef | None = None
    package_sha256: str | None = None
    loaded_at: datetime | None = None
    error: str | None = None


class DriftMeasure(Contract):
    feature: str = Field(description="e.g. score, brightness, decision_rate")
    method: Literal["psi", "ks", "chi2", "mean_shift"]
    value: float
    threshold: float
    alert: bool


class MonitoringMetrics(Contract):
    station_id: StationId | None = Field(default=None, description="None = all stations")
    use_case: UseCase
    model: ModelRef
    window_start: datetime
    window_end: datetime
    n_inferences: int = Field(ge=0)
    decision_rates: dict[str, float] = Field(default_factory=dict)
    mean_score: float | None = None
    latency_ms_p95: float | None = None
    human_agreement_rate: float | None = Field(
        default=None, description="Share of human-reviewed parts where human == AI"
    )
    drift: list[DriftMeasure] = Field(default_factory=list)


class RetrainingPolicy(Contract):
    """When to retrain automatically. Deployment ALWAYS needs a human approval."""

    use_case: UseCase
    enabled: bool = False
    min_new_labels: int | None = Field(default=None, ge=1)
    max_drift_alerts: int | None = Field(default=None, ge=1)
    min_human_agreement: float | None = Field(default=None, ge=0, le=1)
    schedule_cron: str | None = None
    auto_train: bool = False
    deployment_requires_approval: Literal[True] = True
