"""FAKE safety analyzer: simulates PPE (helmet, vest, glasses, gloves) and phone detection.

It ignores the pixels. Results are reproducible (seed + frame_id). By design it outputs
NO identity data and NO face image: only per-person PPE states.

To plug a real model, see ``usecases/safety/README.md``.
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
    FrameMeta,
    PersonPPE,
    PPEState,
    SafetyDetails,
    UseCase,
)

PPE_ITEMS = ("helmet", "vest", "glasses", "gloves")


class FakeSafetyAnalyzer(Analyzer):
    use_case = UseCase.SAFETY
    name = "fake-safety"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.seed = int(config.get("seed", 0))
        self.anomaly_rate = float(config.get("anomaly_rate", 0.08))
        self.min_latency_ms = float(config.get("min_latency_ms", 0))
        self.max_latency_ms = float(config.get("max_latency_ms", 0))
        self.max_persons = int(config.get("max_persons", 3))

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        rng = random.Random(f"{self.seed}-{self.use_case}-{meta.frame_id}")
        time.sleep(rng.uniform(self.min_latency_ms, self.max_latency_ms) / 1000)

        n_persons = rng.randint(1, self.max_persons)
        persons = []
        for i in range(n_persons):
            x1 = i / n_persons + 0.02
            persons.append(
                PersonPPE(
                    person_index=i,
                    bbox=BBox(x1=x1, y1=0.1, x2=x1 + 0.8 / n_persons, y2=0.95),
                    helmet=PPEState.PRESENT,
                    vest=PPEState.PRESENT,
                    glasses=PPEState.PRESENT,
                    gloves=PPEState.PRESENT,
                    phone=False,
                )
            )

        if rng.random() < self.anomaly_rate:
            score = rng.uniform(0.55, 1.0)
        else:
            score = rng.betavariate(2, 7)

        # Make the details consistent with the score.
        culprit = rng.choice(persons)
        if score >= 0.55:
            if rng.random() < 0.3:
                culprit.phone = True
            else:
                setattr(culprit, rng.choice(PPE_ITEMS), PPEState.ABSENT)
        elif score >= 0.35:
            setattr(culprit, rng.choice(PPE_ITEMS), PPEState.UNCERTAIN)

        return AnalysisResult(
            use_case=self.use_case,
            score=score,
            model_name=self.name,
            model_version=self.version,
            details=SafetyDetails(person_count=n_persons, persons=persons),
        )
