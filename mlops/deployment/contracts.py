"""API contracts for deliberate, traceable model lifecycle operations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DecisionValue = Literal["approved", "rejected"]
OperationKind = Literal["deploy", "rollback"]
OperationStatus = Literal[
    "prepared", "requesting", "updating", "verifying", "succeeded", "failed", "uncertain", "expired"
]


class LifecycleError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


class DecisionRequest(BaseModel):
    decision: DecisionValue
    reason: str = Field(min_length=3, max_length=500)
    author_declared: str = Field(min_length=1, max_length=100)
    role_declared: str = Field(default="ai_leader", min_length=1, max_length=50)
    acknowledge_served_rejection: bool = False


class DecisionRecord(BaseModel):
    decision_id: str
    model_id: str
    version: str
    decision: DecisionValue
    reason: str
    author_declared: str
    role_declared: str
    authenticated_identity: None = None
    served_when_decided: bool | None
    status: Literal["requesting", "applied", "uncertain"]
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    requires_serving_action: bool = False


class DeploymentPrepareRequest(BaseModel):
    model_id: str
    version: str = Field(pattern=r"^[0-9]+$")
    endpoint: str
    reason: str = Field(min_length=3, max_length=500)
    author_declared: str = Field(min_length=1, max_length=100)
    role_declared: str = Field(default="ai_leader", min_length=1, max_length=50)


class RollbackPrepareRequest(BaseModel):
    source_operation_id: str
    reason: str = Field(min_length=3, max_length=500)
    author_declared: str = Field(min_length=1, max_length=100)
    role_declared: str = Field(default="ai_leader", min_length=1, max_length=50)


class DeploymentConfirmRequest(BaseModel):
    confirmation: str


class DeploymentOperation(BaseModel):
    operation_id: str
    kind: OperationKind
    model_id: str
    registered_model: str
    version: str
    endpoint: str
    previous_version: str
    previous_config: dict[str, Any]
    requested_config: dict[str, Any]
    expected_fingerprint: str
    expected_config_version: int | None
    reason: str
    author_declared: str
    role_declared: str
    authenticated_identity: None = None
    source_operation_id: str | None = None
    status: OperationStatus
    confirmation: str
    created_at: str
    updated_at: str
    expires_at: str
    submitted_at: str | None = None
    completed_at: str | None = None
    verification: dict[str, Any] | None = None
    error: str | None = None
    inference_tested: bool = False


class EndpointSnapshot(BaseModel):
    name: str
    ready: str | None
    config_update: str | None
    deployment: str | None
    config_version: int | None
    config: dict[str, Any]
    pending_versions: list[str] = Field(default_factory=list)


class VersionSnapshot(BaseModel):
    model_id: str
    registered_model: str
    version: str
    tags: dict[str, str]
    run_id: str | None = None
