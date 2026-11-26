"""Business contracts of the Production Engine (parts, cycles, shifts, corrections, KPIs).

They live apart from ``visionhub/contracts.py`` on purpose: the inference contracts stay
untouched. An inference event is not a produced part: a ``Part`` only exists when a PLC
cycle is triggered, and it references the inference event that produced its prediction.

Verdict vocabulary:
- ``predicted_verdict`` : what the AI said. Immutable, never overwritten.
- ``effective_verdict`` : the verdict ARGOS currently holds (last human correction, else
  the prediction).
- ``disposition``       : what physically happened to the part. Reported by the industrial
  process; ARGOS never derives it from a verdict.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter, computed_field, model_validator

from visionhub.contracts import Contract, Decision, Score, Thresholds

STATION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
CYCLE_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"

StationId = Annotated[str, Field(pattern=STATION_ID_PATTERN)]
CycleId = Annotated[str, Field(pattern=CYCLE_ID_PATTERN)]


class PartVerdict(StrEnum):
    OK = "OK"
    NOK = "NOK"
    HOLD = "HOLD"
    ERROR = "ERROR"


HumanVerdict = Literal["OK", "NOK"]
ActorRole = Literal["operator", "supervisor", "quality"]
TriggerSource = Literal["plc", "plc_simulated"]


class ErrorCode(StrEnum):
    ANALYZER_UNAVAILABLE = "ANALYZER_UNAVAILABLE"
    ANALYZER_FAILED = "ANALYZER_FAILED"
    IMAGE_DECODE_FAILED = "IMAGE_DECODE_FAILED"
    CAPTURE_FAILED = "CAPTURE_FAILED"


class Disposition(StrEnum):
    UNKNOWN = "UNKNOWN"
    SHIPPED = "SHIPPED"
    QUARANTINED = "QUARANTINED"
    REWORKED = "REWORKED"
    SCRAPPED = "SCRAPPED"


# --------------------------------------------------------------------------- parts


class AIPrediction(Contract):
    """Snapshot of the quality inference that produced a part verdict. Immutable."""

    verdict: PartVerdict
    ai_decision: Decision
    score: Score
    model_name: str
    model_version: str
    thresholds_used: Thresholds
    event_id: str
    latency_ms: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _not_error(self) -> AIPrediction:
        if self.verdict == PartVerdict.ERROR:
            raise ValueError("an AI prediction cannot carry the ERROR verdict")
        return self


class InferenceError(Contract):
    code: ErrorCode
    message: str = Field(max_length=500)


class Part(Contract):
    """One physical part presented by a PLC cycle."""

    part_id: str
    station_id: StationId
    cycle_id: CycleId
    shift_id: str | None
    created_at: datetime
    trigger_source: TriggerSource
    camera_id: str
    image_sha256: str | None
    predicted_verdict: PartVerdict
    prediction: AIPrediction | None
    error: InferenceError | None
    effective_verdict: PartVerdict
    correction_count: int = Field(ge=0)
    disposition: Disposition = Disposition.UNKNOWN
    disposition_note: str | None = None
    disposition_updated_at: datetime | None = None

    @model_validator(mode="after")
    def _prediction_xor_error(self) -> Part:
        if self.predicted_verdict == PartVerdict.ERROR:
            if self.error is None or self.prediction is not None:
                raise ValueError("an ERROR part must carry an error and no prediction")
        else:
            if self.prediction is None or self.error is not None:
                raise ValueError("a non-ERROR part must carry a prediction and no error")
            if self.prediction.verdict != self.predicted_verdict:
                raise ValueError("predicted_verdict must match prediction.verdict")
        return self


# --------------------------------------------------------------------------- corrections


class CorrectionIn(Contract):
    """Human verdict on a part, after looking at the physical part.

    ``expected_current_verdict`` is an optimistic lock: the correction is refused if the
    part changed in the meantime (two screens, double click).
    """

    new_verdict: HumanVerdict
    expected_current_verdict: PartVerdict
    reason: str = Field(min_length=3, max_length=500)
    actor_role: ActorRole
    physical_inspection: bool = Field(
        default=False,
        description="Must be true to correct a HOLD or ERROR part: the part was inspected.",
    )


class Correction(Contract):
    correction_id: str
    part_id: str
    sequence: int = Field(ge=1)
    previous_verdict: PartVerdict
    new_verdict: HumanVerdict
    reason: str
    actor_role: ActorRole
    physical_inspection: bool
    at: datetime


class DispositionIn(Contract):
    disposition: Disposition
    note: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- shifts


class ShiftStart(Contract):
    name: str = Field(min_length=1, max_length=32)
    planned_duration_min: int = Field(default=480, ge=1, le=720)
    target_parts: int = Field(ge=0)


class Shift(Contract):
    shift_id: str
    station_id: StationId
    name: str
    status: Literal["OPEN", "CLOSED"]
    started_at: datetime
    planned_duration_min: int
    target_parts: int
    ended_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_serialized_end(cls, data: Any) -> Any:
        """Accept our own JSON back: ``planned_end_at`` is derived, so it is dropped here
        and recomputed (a value inconsistent with the other fields is rejected below)."""
        if not (isinstance(data, dict) and "planned_end_at" in data):
            return data
        data = dict(data)
        received = data.pop("planned_end_at")
        try:
            to_datetime = TypeAdapter(datetime).validate_python
            expected = to_datetime(data["started_at"]) + timedelta(
                minutes=int(data["planned_duration_min"])
            )
            consistent = to_datetime(received) == expected
        except (KeyError, TypeError, ValueError):
            return data  # let the field validation report the real problem
        if not consistent:
            raise ValueError("planned_end_at must equal started_at + planned_duration_min")
        return data

    @computed_field
    @property
    def planned_end_at(self) -> datetime:
        return self.started_at + timedelta(minutes=self.planned_duration_min)


# --------------------------------------------------------------------------- KPIs


class ProductionKPI(Contract):
    """Production indicators over a window. Rates are None when their denominator is 0.

    Counts use the EFFECTIVE verdict; ``predicted_*`` counts keep the AI view.
    HOLD and ERROR parts are never counted as OK nor as NOK.
    """

    window_start: datetime
    window_end: datetime
    elapsed_s: float = Field(ge=0.0)

    total_parts: int
    ok_parts: int
    nok_parts: int
    hold_parts: int
    error_parts: int
    predicted_ok_parts: int
    predicted_nok_parts: int
    predicted_hold_parts: int
    predicted_error_parts: int
    corrected_parts: int

    yield_rate: float | None
    nok_rate: float | None
    pending_rate: float | None
    correction_rate: float | None

    target_parts: int | None
    target_progress: float | None
    actual_total_rate_per_hour: float | None
    actual_ok_rate_per_hour: float | None
    expected_ok_rate_per_hour: float | None
    expected_ok_parts_by_now: float | None
    efficiency: float | None

    mean_latency_ms: float | None


class ShiftReport(Contract):
    shift: Shift
    kpi: ProductionKPI
