"""Retraining policy DTOs (MLOps-specific: the shared Core contracts are NOT changed)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ConditionKind = Literal["drift", "annotations", "performance", "schedule", "manual"]
ConditionState = Literal["satisfied", "not_satisfied", "unavailable"]
Origin = Literal["real", "simulated"]


class DriftParams(BaseModel):
    min_windows: int = Field(2, ge=2, le=30, description="distinct daily windows in a row")
    min_level: Literal["alert", "watch"] = "alert"
    allowed_origins: list[Origin] = Field(default_factory=lambda: ["real"])


class AnnotationParams(BaseModel):
    min_new: int = Field(50, ge=1, le=100_000)


class PerformanceParams(BaseModel):
    metric: str = "recall_nok"
    max_drop: float = Field(0.05, gt=0, le=1)


class ScheduleParams(BaseModel):
    interval_days: int = Field(30, ge=1, le=365)


class Condition(BaseModel):
    kind: ConditionKind
    enabled: bool = False
    required: bool = False  # OR mode: an unavailable / unmet required condition blocks
    drift: DriftParams = Field(default_factory=DriftParams)
    annotations: AnnotationParams = Field(default_factory=AnnotationParams)
    performance: PerformanceParams = Field(default_factory=PerformanceParams)
    schedule: ScheduleParams = Field(default_factory=ScheduleParams)


class Guardrails(BaseModel):
    max_runs_per_month: int = Field(2, ge=0, le=100)
    min_hours_between: int = Field(72, ge=0, le=24 * 365)
    allowed_hours: tuple[int, int] | None = Field(
        None, description="[start, end) local hours; start > end crosses midnight; None = any"
    )
    cpu_only: Literal[True] = True
    allow_concurrent: Literal[False] = False

    @model_validator(mode="after")
    def _hours(self) -> Guardrails:
        if self.allowed_hours is not None:
            start, end = self.allowed_hours
            if not (0 <= start <= 23 and 0 <= end <= 24) or start == end:
                raise ValueError(
                    "allowed_hours must be [start, end) with 0 <= start < 24, end <= 24"
                )
        return self


class DatasetSelection(BaseModel):
    strategy: Literal["latest_published", "pinned"] = "latest_published"
    pinned_version: str | None = None

    @model_validator(mode="after")
    def _pinned(self) -> DatasetSelection:
        if self.strategy == "pinned" and not self.pinned_version:
            raise ValueError("pinned strategy requires pinned_version")
        return self


class PolicyInput(BaseModel):
    """What the AI Leader edits; the server adds identity, version and code version."""

    name: str = Field(min_length=3, max_length=120)
    use_case: str
    model_id: str
    pipeline_id: str
    dataset_family: str
    dataset_selection: DatasetSelection = Field(default_factory=DatasetSelection)
    active: bool = False
    mode: Literal["manual", "auto"] = "manual"
    logic: Literal["AND", "OR"] = "OR"
    conditions: list[Condition] = Field(default_factory=list)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    comment: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _unique_kinds(self) -> PolicyInput:
        kinds = [c.kind for c in self.conditions]
        if len(kinds) != len(set(kinds)):
            raise ValueError("each condition kind may appear only once")
        return self


class RetrainPolicyConfig(PolicyInput):
    policy_id: str
    version: int = Field(ge=1)
    code_version: str  # scientific code commit of the pipeline when this version was saved
    created_at: str
    author: str


class ConditionResult(BaseModel):
    kind: ConditionKind
    required: bool
    state: ConditionState
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_key: str | None = None  # identity of what satisfied it (dedupes proposals)
    simulated: bool = False


class GuardResult(BaseModel):
    name: str
    ok: bool
    detail: str


class Evaluation(BaseModel):
    evaluation_id: str
    policy_id: str
    policy_version: int
    at: str
    trigger: Literal["explicit", "scheduler", "launch_check"]
    logic: Literal["AND", "OR"]
    conditions: list[ConditionResult]
    eligible: bool
    reason: str
    target_dataset_version: str | None
    guards: list[GuardResult] = Field(default_factory=list)
    proposal_id: str | None = None


class Proposal(BaseModel):
    proposal_id: str
    policy_id: str
    policy_version: int
    evidence_key: str
    status: Literal["pending", "accepted", "launching", "launched", "uncertain", "rejected"]
    created_at: str
    updated_at: str
    mode: Literal["manual", "auto"]
    model_id: str
    pipeline_id: str
    dataset_family: str
    dataset_version: str
    reasons: list[str]
    conditions: list[ConditionResult]
    simulated: bool = False
    decided_by: str | None = None
    decision_note: str | None = None
    idempotency_key: str | None = None
    job_run_id: int | None = None
    last_error: str | None = None
