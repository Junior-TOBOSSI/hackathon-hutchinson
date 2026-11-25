"""Tests specific to the quality use case. Adapt them when the real model arrives."""

import numpy as np

from usecases.quality.analyzer import FakeQualityAnalyzer
from visionhub.contracts import Decision, FrameMeta, Thresholds
from visionhub.decision import decide

IMAGE = np.zeros((240, 320, 3), dtype=np.uint8)


def make(seed=42):
    analyzer = FakeQualityAnalyzer()
    analyzer.load({"seed": seed, "anomaly_rate": 0.08, "device": "cpu"})
    return analyzer


def meta(i):
    return FrameMeta(frame_id=str(i), workstation_id="WS", camera_id="C")


def test_reproducible_with_same_seed():
    a, b = make(), make()
    assert [a.analyze(IMAGE, meta(i)).score for i in range(20)] == [
        b.analyze(IMAGE, meta(i)).score for i in range(20)
    ]


def test_mostly_conforming_with_all_three_decisions():
    analyzer, t = make(), Thresholds(low=0.4, high=0.7)
    decisions = [decide(analyzer.analyze(IMAGE, meta(i)).score, t) for i in range(400)]
    share_ok = decisions.count(Decision.CONFORME) / len(decisions)
    assert share_ok > 0.6
    assert {Decision.A_VERIFIER, Decision.ANOMALIE} <= set(decisions)


def test_zones_appear_for_high_scores():
    analyzer = make()
    for i in range(200):
        result = analyzer.analyze(IMAGE, meta(i))
        if result.score >= 0.7:
            assert result.details.zones
