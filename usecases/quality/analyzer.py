"""FAKE quality analyzer: produces plausible results without any model.

It ignores the pixels. Results are reproducible: the random generator is seeded with
``seed`` + ``frame_id``. Most frames are conforming, a few are anomalous.

To plug a real model, see ``usecases/quality/README.md``.
"""

from __future__ import annotations

import random
import time
from typing import Any

import numpy as np

from visionhub.analyzer import Analyzer
from visionhub.contracts import (
    AnalysisResult,
    AnomalyZone,
    BBox,
    FrameMeta,
    QualityDetails,
    UseCase,
)


def random_bbox(rng: random.Random, max_size: float = 0.25) -> BBox:
    w, h = rng.uniform(0.03, max_size), rng.uniform(0.03, max_size)
    x1, y1 = rng.uniform(0, 1 - w), rng.uniform(0, 1 - h)
    return BBox(x1=x1, y1=y1, x2=x1 + w, y2=y1 + h)


class FakeQualityAnalyzer(Analyzer):
    use_case = UseCase.QUALITY
    name = "fake-quality"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.seed = int(config.get("seed", 0))
        self.anomaly_rate = float(config.get("anomaly_rate", 0.08))
        self.min_latency_ms = float(config.get("min_latency_ms", 0))
        self.max_latency_ms = float(config.get("max_latency_ms", 0))

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        rng = random.Random(f"{self.seed}-{self.use_case}-{meta.frame_id}")
        time.sleep(rng.uniform(self.min_latency_ms, self.max_latency_ms) / 1000)

        # Mostly low scores (beta distribution, mean ~0.22), sometimes a clear anomaly.
        if rng.random() < self.anomaly_rate:
            score = rng.uniform(0.55, 1.0)
        else:
            score = rng.betavariate(2, 7)

        zones = []
        if score >= 0.3:
            zones.append(AnomalyZone(bbox=random_bbox(rng), score=score))
            for _ in range(rng.randint(0, 2)):
                zones.append(AnomalyZone(bbox=random_bbox(rng), score=score * rng.uniform(0.5, 1)))

        return AnalysisResult(
            use_case=self.use_case,
            score=score,
            model_name=self.name,
            model_version=self.version,
            details=QualityDetails(zones=zones, heatmap_ref=None),
        )
