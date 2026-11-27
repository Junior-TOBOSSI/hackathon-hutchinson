"""FAKE workstation analyzer: compares a simulated detection with the expected layout.

It ignores the pixels. Results are reproducible (seed + frame_id). Most frames match the
reference; sometimes an object is misplaced or missing.

To plug a real model, see ``usecases/workstation/README.md``.
"""

from __future__ import annotations

import random
import time
from typing import Any

import numpy as np

from visionhub.analyzer import Analyzer
from visionhub.contracts import (
    AnalysisResult,
    BBox,
    DetectedObject,
    FrameMeta,
    UseCase,
    WorkstationDetails,
)

DEFAULT_EXPECTED = ["screwdriver", "gauge", "parts_tray", "torque_wrench"]


class FakeWorkstationAnalyzer(Analyzer):
    use_case = UseCase.WORKSTATION
    name = "fake-workstation"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.seed = int(config.get("seed", 0))
        self.anomaly_rate = float(config.get("anomaly_rate", 0.08))
        self.min_latency_ms = float(config.get("min_latency_ms", 0))
        self.max_latency_ms = float(config.get("max_latency_ms", 0))
        self.expected = list(config.get("expected_objects", DEFAULT_EXPECTED))

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        rng = random.Random(f"{self.seed}-{self.use_case}-{meta.frame_id}")
        time.sleep(rng.uniform(self.min_latency_ms, self.max_latency_ms) / 1000)

        if rng.random() < self.anomaly_rate:
            score = rng.uniform(0.55, 1.0)
        else:
            score = rng.betavariate(2, 7)

        # Make the details consistent with the score.
        objects = list(self.expected)
        rng.shuffle(objects)
        n_missing = 0 if score < 0.55 else (1 if score < 0.8 else 2)
        n_misplaced = 1 if 0.35 <= score else 0
        missing = objects[:n_missing]
        misplaced = objects[n_missing : n_missing + n_misplaced]

        detected = []
        slot_width = 1 / max(len(self.expected), 1)
        for i, label in enumerate(self.expected):
            if label in missing:
                continue
            x1 = i * slot_width + 0.02
            if label in misplaced:  # shifted away from its reference slot
                x1 = min(x1 + rng.uniform(0.1, 0.3), 1 - slot_width)
            detected.append(
                DetectedObject(
                    label=label,
                    confidence=rng.uniform(0.6, 0.99),
                    bbox=BBox(x1=x1, y1=0.6, x2=x1 + slot_width * 0.8, y2=0.9),
                )
            )

        return AnalysisResult(
            use_case=self.use_case,
            score=score,
            model_name=self.name,
            model_version=self.version,
            details=WorkstationDetails(
                expected=self.expected, detected=detected, missing=missing, misplaced=misplaced
            ),
        )
