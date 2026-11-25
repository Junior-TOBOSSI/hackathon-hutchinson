"""The analysis chain: source -> preprocessing -> analyzers -> decision -> storage.

``process_frame`` handles one image (also used by POST /analyze).
``start`` runs the loop in a background thread at PIPELINE_FPS.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable

import numpy as np

from visionhub.config import Settings
from visionhub.contracts import Event, FrameMeta, UseCase
from visionhub.decision import to_event
from visionhub.preprocess import preprocess
from visionhub.registry import Registry
from visionhub.sources import open_source
from visionhub.store import EventStore

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings, registry: Registry, store: EventStore) -> None:
        self.settings = settings
        self.registry = registry
        self.store = store
        self.frames_processed = 0
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._analyze_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------- one frame

    def process_frame(
        self,
        image: np.ndarray,
        meta: FrameMeta,
        use_cases: Iterable[UseCase] | None = None,
        store: bool = True,
    ) -> list[Event]:
        """Run the selected analyzers (all by default) on one image, return the events."""
        image = preprocess(image, self.settings)
        wanted = set(use_cases) if use_cases is not None else None
        events = []
        for use_case, analyzer in self.registry.ready():
            if wanted is not None and use_case not in wanted:
                continue
            start = time.perf_counter()
            try:
                # The background loop and POST /analyze may call the same model at the same
                # time; many real models are not thread-safe, so calls are serialized.
                with self._analyze_lock:
                    result = analyzer.analyze(image, meta)
            except Exception:
                # One failing analyzer must not stop the others.
                log.exception("Analyzer %s failed on frame %s", use_case, meta.frame_id)
                continue
            latency_ms = (time.perf_counter() - start) * 1000
            result = result.model_copy(update={"latency_ms": latency_ms})
            event = to_event(result, meta, self.registry.thresholds(use_case))
            if store:
                self.store.add(event)
            events.append(event)
        return events

    # ------------------------------------------------------------- background loop

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        period = 1.0 / self.settings.pipeline_fps
        try:
            source = open_source(self.settings)
            for image in source:
                if self._stop.is_set():
                    break
                start = time.perf_counter()
                meta = FrameMeta(
                    frame_id=f"{self.settings.camera_id}-{self.frames_processed:06d}",
                    workstation_id=self.settings.workstation_id,
                    camera_id=self.settings.camera_id,
                )
                self.process_frame(image, meta)
                self.frames_processed += 1
                # Keep the requested frame rate.
                self._stop.wait(max(0.0, period - (time.perf_counter() - start)))
        except Exception as exc:
            self.last_error = repr(exc)
            log.exception("Pipeline stopped")
