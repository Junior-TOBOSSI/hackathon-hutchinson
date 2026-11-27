"""Isolated Edge entry point for a time-compressed demonstration shift.

Only shift opening uses the configured 08:00 start. Production cycles, corrections
and outbox events keep the real clock so Core's rolling KPIs stay meaningful.
"""

from __future__ import annotations

import os
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from pydantic import BaseModel

from visionhub.argos_app import create_argos_app
from visionhub.contracts import utc_now
from visionhub.production.contracts import Shift, ShiftStart, StationId


class DemoShiftName(BaseModel):
    name: str


class DemoShiftClock:
    """Expose an accelerated planning clock without changing production timestamps."""

    def __init__(self, start: str, duration_min: int, target_parts: int, runtime_s: float):
        hour, minute = (int(value) for value in start.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("HOVIS_DEMO_SHIFT_START must be HH:MM")
        if not (1 <= duration_min <= 720 and target_parts > 0 and runtime_s > 0):
            raise ValueError("invalid demo shift duration, target or runtime")
        self.hour = hour
        self.minute = minute
        self.duration_min = duration_min
        self.target_parts = target_parts
        self.runtime_s = runtime_s
        self._opening_at: ContextVar[datetime | None] = ContextVar("demo_opening_at", default=None)
        self._runs: dict[str, tuple[datetime, float]] = {}
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        return self._opening_at.get() or utc_now()

    def open(self, request: Request, station_id: StationId, name: str) -> Shift:
        with self._lock:
            if name not in self._runs:
                local = datetime.now().astimezone()
                start = local.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
                self._runs[name] = (start, time.monotonic())
            start, _ = self._runs[name]
        token = self._opening_at.set(start)
        try:
            return request.app.state.production.start_shift(
                station_id,
                ShiftStart(
                    name=name,
                    planned_duration_min=self.duration_min,
                    target_parts=self.target_parts,
                ),
            )
        finally:
            self._opening_at.reset(token)

    def state(self, name: str) -> dict[str, str | int | float]:
        with self._lock:
            run = self._runs.get(name)
        if run is None:
            raise HTTPException(404, "unknown demo shift")
        start, real_start = run
        elapsed = min(1.0, max(0.0, (time.monotonic() - real_start) / self.runtime_s))
        now = start + timedelta(minutes=self.duration_min * elapsed)
        return {
            "now": now.isoformat(),
            "started_at": start.isoformat(),
            "planned_end_at": (start + timedelta(minutes=self.duration_min)).isoformat(),
            "target_parts": self.target_parts,
            "runtime_s": self.runtime_s,
        }


demo_clock = DemoShiftClock(
    os.environ.get("HOVIS_DEMO_SHIFT_START", "08:00"),
    int(os.environ.get("HOVIS_DEMO_SHIFT_DURATION_MIN", "480")),
    int(os.environ.get("HOVIS_DEMO_SHIFT_TARGET", "1000")),
    float(os.environ.get("HOVIS_DEMO_SHIFT_RUNTIME_SEC", "180")),
)
app = create_argos_app(clock=demo_clock)


@app.get("/production/demo-shift-config")
def demo_shift_config() -> dict[str, str | int | float]:
    return {
        "start": f"{demo_clock.hour:02d}:{demo_clock.minute:02d}",
        "planned_duration_min": demo_clock.duration_min,
        "target_parts": demo_clock.target_parts,
        "runtime_s": demo_clock.runtime_s,
    }


@app.post("/production/demo/stations/{station_id}/shifts", status_code=201)
def start_demo_shift(request: Request, station_id: StationId, body: DemoShiftName) -> Shift:
    if not body.name.startswith("DEMO-") or len(body.name) > 32:
        raise HTTPException(422, "demo shift name must start with DEMO-")
    return demo_clock.open(request, station_id, body.name)


@app.get("/production/demo-shift-clock")
def demo_shift_now(name: str) -> dict[str, str | int | float]:
    return demo_clock.state(name)
