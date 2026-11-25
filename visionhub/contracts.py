"""Data contracts shared by every part of the platform.

This file is the heart of the repository: sources, analyzers, the decision layer,
the API and the dashboard all exchange these objects. Do not change it without
the agreement of the whole team.

Conventions:
- ``score`` is always in [0, 1] and HIGHER MEANS WORSE (more anomalous / more risky).
- Bounding boxes are NORMALIZED to [0, 1] (x1, y1 = top-left, x2, y2 = bottom-right),
  so they do not depend on the image resolution.
- Every model forbids unknown fields (``extra="forbid"``): nobody can silently add,
  for example, a face crop or an identity field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Score = Annotated[float, Field(ge=0.0, le=1.0)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    """Base class: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- enums


class UseCase(StrEnum):
    QUALITY = "quality"
    WORKSTATION = "workstation"
    SAFETY = "safety"


class Decision(StrEnum):
    CONFORME = "conforme"
    A_VERIFIER = "a_verifier"
    ANOMALIE = "anomalie"


class PPEState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"


# --------------------------------------------------------------------------- input


class FrameMeta(Contract):
    """Metadata of one image coming from a source."""

    frame_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    workstation_id: str
    camera_id: str


class BBox(Contract):
    """Normalized bounding box, coordinates in [0, 1]."""

    x1: Score
    y1: Score
    x2: Score
    y2: Score

    @model_validator(mode="after")
    def _ordered(self) -> BBox:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError("bbox must satisfy x1 <= x2 and y1 <= y2")
        return self


# --------------------------------------------------------------------------- details


class AnomalyZone(Contract):
    bbox: BBox
    score: Score


class QualityDetails(Contract):
    kind: Literal["quality"] = "quality"
    zones: list[AnomalyZone] = Field(default_factory=list)
    heatmap_ref: str | None = Field(
        default=None, description="Optional reference (path/URL) to a heatmap. Never inline."
    )


class DetectedObject(Contract):
    label: str
    confidence: Score
    bbox: BBox


class WorkstationDetails(Contract):
    kind: Literal["workstation"] = "workstation"
    expected: list[str] = Field(default_factory=list)
    detected: list[DetectedObject] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    misplaced: list[str] = Field(default_factory=list)


class PersonPPE(Contract):
    """One detected person. Position in the image only: NO identity, NO face data."""

    person_index: int = Field(ge=0, description="Index in this frame only, not a tracking id")
    bbox: BBox | None = None
    helmet: PPEState
    vest: PPEState
    glasses: PPEState
    gloves: PPEState
    phone: bool


class SafetyDetails(Contract):
    kind: Literal["safety"] = "safety"
    person_count: int = Field(ge=0)
    persons: list[PersonPPE] = Field(default_factory=list)


Details = Annotated[
    QualityDetails | WorkstationDetails | SafetyDetails, Field(discriminator="kind")
]


# --------------------------------------------------------------------------- outputs


class AnalysisResult(Contract):
    """Output of an analyzer (before the decision layer)."""

    use_case: UseCase
    score: Score
    latency_ms: float = Field(default=0.0, ge=0.0, description="Filled in by the pipeline")
    model_name: str
    model_version: str
    details: Details

    @model_validator(mode="after")
    def _details_match_use_case(self) -> AnalysisResult:
        if self.details.kind != self.use_case.value:
            raise ValueError(
                f"details.kind={self.details.kind!r} does not match use_case={self.use_case.value!r}"
            )
        return self


class Thresholds(Contract):
    """Two thresholds per use case: score < low -> conforme, score >= high -> anomalie."""

    low: Score
    high: Score

    @model_validator(mode="after")
    def _low_le_high(self) -> Thresholds:
        if self.low > self.high:
            raise ValueError("low must be <= high")
        return self


class FeedbackIn(Contract):
    """Operator verdict, as sent to the API."""

    verdict: Literal["conforme", "defaut"]
    comment: str | None = Field(default=None, max_length=500)


class OperatorFeedback(FeedbackIn):
    at: datetime = Field(default_factory=utc_now)


class Event(AnalysisResult):
    """An analysis result after the decision layer: this is what is stored and served."""

    event_id: str
    frame: FrameMeta
    decision: Decision
    thresholds_used: Thresholds
    operator_feedback: OperatorFeedback | None = None


class UseCaseInfo(Contract):
    """Description of a loaded use case, served by GET /use-cases."""

    use_case: UseCase
    status: Literal["ok", "error"]
    analyzer_class: str
    name: str | None = None
    version: str | None = None
    thresholds: Thresholds
    error: str | None = None
