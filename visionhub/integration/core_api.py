"""Read models served by ARGOS Core (to be developed) to the Supervisor and AI Leader UIs.

They are built from the Edge events (see edge_events.py). The frontend uses them in mock
mode until Core exists; their JSON Schemas are exported for TypeScript generation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from visionhub.contracts import Contract, UseCase
from visionhub.integration.edge_events import EquipmentStatusPayload, OperatorReportPayload
from visionhub.integration.mlops import StationDeploymentStatus
from visionhub.production.contracts import ShiftReport, StationId


class StationSummary(Contract):
    station_id: StationId
    name: str
    cell: str
    simulated: bool = Field(description="Simulated stations are shown as such in the UI")
    online: bool
    last_seen_at: datetime | None = None
    current_shift: ShiftReport | None = None
    equipment: list[EquipmentStatusPayload] = Field(default_factory=list)
    models: list[StationDeploymentStatus] = Field(default_factory=list)
    open_alerts: int = Field(default=0, ge=0)


class Alert(Contract):
    """One alert EPISODE (grouped detections), managed by the Alert Manager (ARGOS-02B)."""

    alert_id: str
    station_id: StationId
    camera_id: str | None = None
    use_case: UseCase | None = None
    alert_type: str = Field(description="e.g. ppe.helmet_missing, behavior.phone_use, part.nok")
    severity: Literal["info", "warning", "critical"]
    status: Literal["open", "acknowledged", "validated", "rejected", "resolved"]
    title: str
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int = Field(ge=1)
    max_score: float | None = Field(default=None, ge=0, le=1)
    source_event_ids: list[str] = Field(default_factory=list)
    simulated: bool = False


class OperatorReport(OperatorReportPayload):
    """An operator report as stored by Core (with its station and status)."""

    station_id: StationId
    created_at: datetime
    status: Literal["open", "acknowledged", "closed"] = "open"
