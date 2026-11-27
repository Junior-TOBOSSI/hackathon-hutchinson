"""Optional local scheduler, DISABLED by default.

It runs only when ``HOVIS_RETRAIN_SCHEDULER=1`` at gateway start. Each pass evaluates the
active policies; it launches only for active AUTOMATIC policies, and every launch still goes
through TrainingService.launch, which requires ``HOVIS_TRAINING_REMOTE=1``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

MIN_INTERVAL_S = 300


class Scheduler:
    def __init__(self, tick: Callable[[bool], list[dict[str, Any]]]) -> None:
        self._tick = tick
        self.enabled = os.environ.get("HOVIS_RETRAIN_SCHEDULER") == "1"
        self.interval_s = max(
            MIN_INTERVAL_S, int(os.environ.get("HOVIS_RETRAIN_SCHEDULER_INTERVAL", "3600"))
        )
        self.last_tick: str | None = None
        self.last_result: list[dict[str, Any]] | str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="hovis-retrain-scheduler", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.run_once()

    def run_once(self) -> None:
        self.last_tick = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            self.last_result = self._tick(self.enabled)
        except Exception as exc:  # noqa: BLE001 - reported in the status, the loop continues
            self.last_result = f"{type(exc).__name__}: {str(exc)[:200]}"

    def stop(self) -> None:
        self._stop.set()

    def state(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._thread is not None and self._thread.is_alive(),
            "variable": "HOVIS_RETRAIN_SCHEDULER",
            "interval_s": self.interval_s,
            "last_tick": self.last_tick,
            "last_result": self.last_result,
        }
