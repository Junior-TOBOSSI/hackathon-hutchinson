"""Registry: finds, loads and keeps the analyzers of the enabled use cases.

For each use case, the class to load is declared in ``usecases/<use_case>/config.yaml``:

    analyzer_class: usecases.quality.analyzer:FakeQualityAnalyzer

Swapping the fake analyzer for a real one = changing that line. If an analyzer fails to
load, the error is logged and the use case is reported with status "error": the other
use cases keep running.
"""

from __future__ import annotations

import importlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from visionhub.analyzer import Analyzer
from visionhub.config import USECASES_DIR, Settings, UseCaseConfig, load_use_case_config
from visionhub.contracts import Thresholds, UseCase, UseCaseInfo

log = logging.getLogger(__name__)


def import_class(path: str) -> type:
    """Import 'package.module:ClassName'."""
    module_name, _, class_name = path.partition(":")
    if not class_name:
        raise ValueError(f"analyzer_class must look like 'module:Class', got {path!r}")
    return getattr(importlib.import_module(module_name), class_name)


def build_analyzer(use_case: UseCase, config: UseCaseConfig, device: str) -> Analyzer:
    """Import, check and load the analyzer declared in a use case config."""
    cls = import_class(config.analyzer_class)
    if not (isinstance(cls, type) and issubclass(cls, Analyzer)):
        raise TypeError(f"{config.analyzer_class} is not a subclass of visionhub Analyzer")
    if cls.use_case != use_case:
        raise ValueError(f"{config.analyzer_class}.use_case is {cls.use_case}, expected {use_case}")
    analyzer = cls()
    analyzer.load({**config.params, "device": device})
    return analyzer


@dataclass
class Slot:
    """One use case as seen by the platform."""

    use_case: UseCase
    analyzer_class: str
    thresholds: Thresholds
    analyzer: Analyzer | None = None
    error: str | None = None


class Registry:
    def __init__(self, settings: Settings, base_dir: Path = USECASES_DIR) -> None:
        self._settings = settings
        self._base_dir = base_dir
        self._slots: dict[UseCase, Slot] = {}
        self._lock = threading.Lock()

    def load(self) -> Registry:
        for use_case in self._settings.enabled_use_cases:
            try:
                config = load_use_case_config(use_case, self._base_dir)
            except Exception as exc:  # missing or invalid config.yaml
                log.exception("Cannot read config of use case %s", use_case)
                self._slots[use_case] = Slot(
                    use_case, "?", Thresholds(low=0.5, high=0.5), error=repr(exc)
                )
                continue
            slot = Slot(use_case, config.analyzer_class, config.thresholds)
            try:
                slot.analyzer = build_analyzer(use_case, config, self._settings.device)
                log.info("Loaded %s -> %s", use_case, config.analyzer_class)
            except Exception as exc:
                log.exception("Cannot load analyzer of use case %s", use_case)
                slot.error = repr(exc)
            self._slots[use_case] = slot
        return self

    # ------------------------------------------------------------------ queries

    def ready(self) -> list[tuple[UseCase, Analyzer]]:
        """Use cases whose analyzer is loaded."""
        return [(s.use_case, s.analyzer) for s in self._slots.values() if s.analyzer]

    def get(self, use_case: UseCase) -> Analyzer | None:
        slot = self._slots.get(use_case)
        return slot.analyzer if slot else None

    def thresholds(self, use_case: UseCase) -> Thresholds:
        with self._lock:
            return self._slots[use_case].thresholds

    def set_thresholds(self, use_case: UseCase, thresholds: Thresholds) -> None:
        """Change thresholds at runtime (kept in memory, reset on restart)."""
        if use_case not in self._slots:
            raise KeyError(use_case)
        with self._lock:
            self._slots[use_case].thresholds = thresholds

    def info(self) -> list[UseCaseInfo]:
        out = []
        for s in self._slots.values():
            out.append(
                UseCaseInfo(
                    use_case=s.use_case,
                    status="ok" if s.analyzer else "error",
                    analyzer_class=s.analyzer_class,
                    name=s.analyzer.name if s.analyzer else None,
                    version=s.analyzer.version if s.analyzer else None,
                    thresholds=self.thresholds(s.use_case),
                    error=s.error,
                )
            )
        return out
