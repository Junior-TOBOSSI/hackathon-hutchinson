"""Production Engine: PLC cycles -> quality inspection -> parts; shifts; corrections; KPIs.

Inference goes through the existing ``Pipeline.process_frame`` restricted to the quality
use case, with ``store=False``. That keeps the shared guarantees of the platform
(preprocessing, the analyzer lock shared with the background loop, latency measurement,
decision layer) without modifying the pipeline. The resulting event is then stored
together with the part, in one transaction.

Delivery guarantees (honest version):
- a (station_id, cycle_id) pair never creates two parts (UNIQUE constraint), including
  after a restart and across processes sharing the database;
- a replay of an existing cycle never runs a new inference;
- a part and its inference event are committed atomically: no orphan event, no part
  without its event;
- if the process dies AFTER the inference but BEFORE the commit, nothing is stored and
  the PLC retry runs the inference again (at-least-once inference, at-most-once part).
  Exactly-once inference is NOT guaranteed.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from visionhub.contracts import Event, FrameMeta, UseCase, utc_now
from visionhub.pipeline import Pipeline
from visionhub.production.contracts import (
    AIPrediction,
    CorrectionIn,
    DispositionIn,
    ErrorCode,
    InferenceError,
    Part,
    PartVerdict,
    ProductionKPI,
    Shift,
    ShiftReport,
    ShiftStart,
)
from visionhub.production.kpi import compute_kpi
from visionhub.production.store import (
    ConflictError,
    DuplicateCycleError,
    InvalidOperationError,
    NotFoundError,
    ProductionStore,
)
from visionhub.production.verdicts import verdict_from_decision
from visionhub.registry import Registry
from visionhub.sources import synthetic_frame

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CycleRequest:
    station_id: str
    cycle_id: str
    camera_id: str
    simulated: bool
    image_bytes: bytes | None = None


def simulated_frame(cycle_id: str) -> np.ndarray:
    """Deterministic synthetic image of a SIMULATED cycle (same id -> same image)."""
    index = int(hashlib.sha256(cycle_id.encode()).hexdigest()[:8], 16) % 1_000_000
    return synthetic_frame(index)


class ProductionEngine:
    def __init__(
        self,
        store: ProductionStore,
        registry: Registry,
        pipeline: Pipeline,
        clock: Clock = utc_now,
    ) -> None:
        self.store = store
        self.registry = registry
        self.pipeline = pipeline
        self.clock = clock
        # Serializes cycle creation in this process, so that concurrent triggers of the
        # same cycle run ONE inference. The UNIQUE constraint covers other processes.
        self._cycle_lock = threading.Lock()

    # ------------------------------------------------------------------ cycles

    def run_cycle(self, request: CycleRequest) -> tuple[Part, bool]:
        """Return (part, replayed). ``replayed`` is True when the cycle already existed."""
        image, sha, error = self._acquire(request)
        source = "plc_simulated" if request.simulated else "plc"
        with self._cycle_lock:
            existing = self.store.get_part_by_cycle(request.station_id, request.cycle_id)
            if existing is not None:
                return self._replay(existing, request, source, sha), True

            now = self.clock()
            shift = self.store.current_shift(request.station_id)
            event = None
            if error is None:
                meta = FrameMeta(
                    frame_id=f"cycle:{request.station_id}:{request.cycle_id}",
                    timestamp=now,
                    workstation_id=request.station_id,
                    camera_id=request.camera_id,
                )
                event, error = self._inspect(image, meta)

            if error is not None:
                verdict, prediction = PartVerdict.ERROR, None
            else:
                verdict = verdict_from_decision(event.decision)
                prediction = AIPrediction(
                    verdict=verdict,
                    ai_decision=event.decision,
                    score=event.score,
                    model_name=event.model_name,
                    model_version=event.model_version,
                    thresholds_used=event.thresholds_used,
                    event_id=event.event_id,
                    latency_ms=event.latency_ms,
                )
            part = Part(
                part_id=str(uuid.uuid4()),
                station_id=request.station_id,
                cycle_id=request.cycle_id,
                shift_id=shift.shift_id if shift else None,
                created_at=now,
                trigger_source=source,
                camera_id=request.camera_id,
                image_sha256=sha,
                predicted_verdict=verdict,
                prediction=prediction,
                error=error,
                effective_verdict=verdict,
                correction_count=0,
            )
            try:
                self.store.insert_part(part, event)
            except DuplicateCycleError:
                # Created meanwhile by another process sharing the database.
                existing = self.store.get_part_by_cycle(request.station_id, request.cycle_id)
                return self._replay(existing, request, source, sha), True
            return part, False

    def _acquire(
        self, request: CycleRequest
    ) -> tuple[np.ndarray | None, str | None, InferenceError | None]:
        """Get the image of a cycle. A synthetic image is ONLY used for simulated cycles."""
        if request.image_bytes is not None:
            sha = hashlib.sha256(request.image_bytes).hexdigest()
            buffer = np.frombuffer(request.image_bytes, dtype=np.uint8)
            image = cv2.imdecode(buffer, cv2.IMREAD_COLOR) if buffer.size else None
            if image is None:
                error = InferenceError(
                    code=ErrorCode.IMAGE_DECODE_FAILED,
                    message="the received file cannot be decoded as an image",
                )
                return None, sha, error
            return image, sha, None
        if request.simulated:
            image = simulated_frame(request.cycle_id)
            return image, hashlib.sha256(image.tobytes()).hexdigest(), None
        error = InferenceError(
            code=ErrorCode.CAPTURE_FAILED,
            message="no image received for an industrial cycle (no synthetic fallback)",
        )
        return None, None, error

    def _inspect(
        self, image: np.ndarray, meta: FrameMeta
    ) -> tuple[Event | None, InferenceError | None]:
        if self.registry.get(UseCase.QUALITY) is None:
            return None, InferenceError(
                code=ErrorCode.ANALYZER_UNAVAILABLE, message="the quality analyzer is not loaded"
            )
        try:
            events = self.pipeline.process_frame(image, meta, [UseCase.QUALITY], store=False)
        except Exception as exc:  # e.g. preprocessing failure
            log.exception("Quality inspection failed on %s", meta.frame_id)
            return None, InferenceError(code=ErrorCode.ANALYZER_FAILED, message=repr(exc)[:500])
        if not events:
            # process_frame logs the analyzer exception and returns no event.
            return None, InferenceError(
                code=ErrorCode.ANALYZER_FAILED,
                message="the quality analyzer raised an exception (see the server logs)",
            )
        return events[0], None

    @staticmethod
    def _replay(existing: Part, request: CycleRequest, source: str, sha: str | None) -> Part:
        if (
            existing.image_sha256 != sha
            or existing.trigger_source != source
            or existing.camera_id != request.camera_id
        ):
            raise ConflictError(
                f"cycle {request.cycle_id!r} of station {request.station_id!r} was already "
                "recorded with a different image, camera or trigger source"
            )
        return existing

    # ------------------------------------------------------------------ parts

    def get_part(self, part_id: str) -> Part:
        part = self.store.get_part(part_id)
        if part is None:
            raise NotFoundError(f"unknown part {part_id!r}")
        return part

    def get_part_by_cycle(self, station_id: str, cycle_id: str) -> Part:
        part = self.store.get_part_by_cycle(station_id, cycle_id)
        if part is None:
            raise NotFoundError(f"unknown cycle {cycle_id!r} on station {station_id!r}")
        return part

    def correct(self, part_id: str, body: CorrectionIn) -> Part:
        part, _ = self.store.add_correction(part_id, body, str(uuid.uuid4()), self.clock())
        return part

    def set_disposition(self, part_id: str, body: DispositionIn) -> Part:
        return self.store.set_disposition(part_id, body, self.clock())

    # ------------------------------------------------------------------ shifts

    def start_shift(self, station_id: str, body: ShiftStart) -> Shift:
        shift = Shift(
            shift_id=str(uuid.uuid4()),
            station_id=station_id,
            name=body.name,
            status="OPEN",
            started_at=self.clock(),
            planned_duration_min=body.planned_duration_min,
            target_parts=body.target_parts,
        )
        self.store.insert_shift(shift)
        return shift

    def close_shift(self, shift_id: str) -> ShiftReport:
        self.store.close_shift(shift_id, self.clock())
        return self.shift_report(shift_id)

    def shift_report(self, shift_id: str) -> ShiftReport:
        shift = self.store.get_shift(shift_id)
        if shift is None:
            raise NotFoundError(f"unknown shift {shift_id!r}")
        now = self.clock()
        kpi = compute_kpi(
            self.store.tally(shift_id=shift_id),
            window_start=shift.started_at,
            window_end=shift.ended_at or now,
            now=now,
            target_parts=shift.target_parts,
            planned_duration_min=shift.planned_duration_min,
        )
        return ShiftReport(shift=shift, kpi=kpi)

    def current_shift_report(self, station_id: str) -> ShiftReport:
        shift = self.store.current_shift(station_id)
        if shift is None:
            raise NotFoundError(f"no open shift on station {station_id!r}")
        return self.shift_report(shift.shift_id)

    # ------------------------------------------------------------------ KPIs

    def station_kpi(self, station_id: str, start: datetime, end: datetime) -> ProductionKPI:
        if start > end:
            raise InvalidOperationError("'from' must be before 'to'")
        return compute_kpi(
            self.store.tally(station_id=station_id, start=start, end=end),
            window_start=start,
            window_end=end,
            now=self.clock(),
        )
