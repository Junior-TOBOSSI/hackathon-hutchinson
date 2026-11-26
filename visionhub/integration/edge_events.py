"""Edge -> Core event contract, version ``argos.edge-event/1``.

Every fact produced on a station (inference, part, correction, shift, operator report,
equipment or model status) is written to a local SQLite outbox in the SAME transaction
as the fact itself, then pushed to ARGOS Core in batches. Core acknowledges each event.

Rules:
- ``event_id`` (UUID) is the idempotency key: Core stores each event_id at most once and
  answers ``duplicate`` for replays.
- ``edge_sequence`` is strictly increasing per station: the outbox is sent in order and
  Core can detect gaps.
- Corrections of one part carry ``correction.sequence``: Core applies the highest one,
  so the effective verdict is right whatever the arrival order.
- No image, no face, no person identity ever travels in an event.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from visionhub.contracts import Contract, Decision, Event, Score, UseCase
from visionhub.production.contracts import (
    STATION_ID_PATTERN,
    ActorRole,
    Correction,
    Disposition,
    Part,
    PartVerdict,
    Shift,
    StationId,
)

SCHEMA_VERSION = "argos.edge-event/1"


class EdgeEventType(StrEnum):
    INFERENCE = "inference"
    PART_RECORDED = "part.recorded"
    PART_CORRECTED = "part.corrected"
    PART_DISPOSITION = "part.disposition"
    SHIFT_OPENED = "shift.opened"
    SHIFT_CLOSED = "shift.closed"
    OPERATOR_REPORT = "operator.report"
    EQUIPMENT_STATUS = "equipment.status"
    MODEL_STATUS = "model.status"


# --------------------------------------------------------------------------- payloads


class InferencePayload(Contract):
    kind: Literal["inference"] = "inference"
    event: Event  # the historical inference event, unchanged (no image inside)


class PartRecordedPayload(Contract):
    kind: Literal["part.recorded"] = "part.recorded"
    part: Part


class PartCorrectedPayload(Contract):
    kind: Literal["part.corrected"] = "part.corrected"
    correction: Correction


class PartDispositionPayload(Contract):
    kind: Literal["part.disposition"] = "part.disposition"
    part_id: str
    disposition: Disposition
    note: str | None = Field(default=None, max_length=500)


class ShiftPayload(Contract):
    kind: Literal["shift"] = "shift"
    shift: Shift


class OperatorReportPayload(Contract):
    """A problem reported by the operator to the supervisor. Free text, no identity."""

    kind: Literal["operator.report"] = "operator.report"
    report_id: str
    category: Literal["quality", "safety", "workstation", "equipment", "other"]
    severity: Literal["info", "warning", "critical"]
    message: str = Field(min_length=1, max_length=500)
    actor_role: ActorRole = "operator"
    related_part_id: str | None = None
    related_event_id: str | None = None


class EquipmentStatusPayload(Contract):
    kind: Literal["equipment.status"] = "equipment.status"
    equipment_id: str
    equipment_type: Literal["camera", "plc", "edge", "model_runtime"]
    status: Literal["ok", "degraded", "down", "unknown"]
    detail: str | None = Field(default=None, max_length=500)


class ModelStatusPayload(Contract):
    """Which model version a station actually runs (reported after each (re)load)."""

    kind: Literal["model.status"] = "model.status"
    use_case: UseCase
    model_name: str
    model_version: str
    package_sha256: str | None = None
    loaded: bool
    error: str | None = Field(default=None, max_length=500)


EdgePayload = Annotated[
    InferencePayload
    | PartRecordedPayload
    | PartCorrectedPayload
    | PartDispositionPayload
    | ShiftPayload
    | OperatorReportPayload
    | EquipmentStatusPayload
    | ModelStatusPayload,
    Field(discriminator="kind"),
]

PAYLOAD_KIND = {
    EdgeEventType.INFERENCE: "inference",
    EdgeEventType.PART_RECORDED: "part.recorded",
    EdgeEventType.PART_CORRECTED: "part.corrected",
    EdgeEventType.PART_DISPOSITION: "part.disposition",
    EdgeEventType.SHIFT_OPENED: "shift",
    EdgeEventType.SHIFT_CLOSED: "shift",
    EdgeEventType.OPERATOR_REPORT: "operator.report",
    EdgeEventType.EQUIPMENT_STATUS: "equipment.status",
    EdgeEventType.MODEL_STATUS: "model.status",
}


# --------------------------------------------------------------------------- envelope


class EdgeEvent(Contract):
    """Envelope of every Edge -> Core event. Header fields are copied from the payload
    so that Core can index and route events without parsing every payload kind."""

    schema_version: Literal["argos.edge-event/1"] = SCHEMA_VERSION
    event_id: str = Field(min_length=8, max_length=64, description="UUID, idempotency key")
    event_type: EdgeEventType
    station_id: StationId
    edge_sequence: int = Field(ge=1, description="Strictly increasing per station")
    occurred_at: datetime = Field(description="UTC, timezone-aware")
    simulated: bool = False
    camera_id: str | None = None
    cycle_id: str | None = None
    part_id: str | None = None
    use_case: UseCase | None = None
    model_name: str | None = None
    model_version: str | None = None
    score: Score | None = None
    decision: Decision | None = None
    verdict: PartVerdict | None = None
    payload: EdgePayload

    @model_validator(mode="after")
    def _consistent(self) -> EdgeEvent:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset().total_seconds():
            raise ValueError("occurred_at must be a UTC timezone-aware datetime")
        if self.payload.kind != PAYLOAD_KIND[self.event_type]:
            raise ValueError(
                f"payload kind {self.payload.kind!r} does not match event_type "
                f"{self.event_type.value!r}"
            )
        return self


class EdgeEventBatch(Contract):
    """POST /ingest/v1/events body. Events are sorted by edge_sequence."""

    station_id: Annotated[str, Field(pattern=STATION_ID_PATTERN)]
    sent_at: datetime
    events: list[EdgeEvent] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _same_station_sorted(self) -> EdgeEventBatch:
        if any(e.station_id != self.station_id for e in self.events):
            raise ValueError("every event of a batch must belong to the batch station")
        sequences = [e.edge_sequence for e in self.events]
        if sequences != sorted(set(sequences)):
            raise ValueError("events must be sorted by strictly increasing edge_sequence")
        return self


class IngestResult(Contract):
    event_id: str
    status: Literal["accepted", "duplicate", "rejected"]
    error: str | None = None


class IngestAck(Contract):
    """Core answer. The Edge marks ``accepted`` and ``duplicate`` events as delivered;
    ``rejected`` events stay in the outbox flagged for investigation (never dropped)."""

    station_id: str
    received_at: datetime
    results: list[IngestResult]
    highest_contiguous_sequence: int = Field(
        ge=0, description="Highest edge_sequence such that all previous ones are stored"
    )
