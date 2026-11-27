"""Tests specific to the workstation use case. Adapt them when the real model arrives."""

import numpy as np

from usecases.workstation.analyzer import FakeWorkstationAnalyzer
from visionhub.contracts import Decision, FrameMeta, Thresholds
from visionhub.decision import decide

IMAGE = np.zeros((240, 320, 3), dtype=np.uint8)
EXPECTED = ["a", "b", "c"]


def make(seed=7):
    analyzer = FakeWorkstationAnalyzer()
    analyzer.load({"seed": seed, "expected_objects": EXPECTED, "device": "cpu"})
    return analyzer


def meta(i):
    return FrameMeta(frame_id=str(i), workstation_id="WS", camera_id="C")


def test_details_are_consistent():
    analyzer = make()
    for i in range(200):
        d = analyzer.analyze(IMAGE, meta(i)).details
        detected = {o.label for o in d.detected}
        assert d.expected == EXPECTED
        assert set(d.missing).isdisjoint(detected)
        assert set(d.missing) | detected == set(EXPECTED)
        assert set(d.misplaced) <= detected


def test_mostly_conforming_with_all_three_decisions():
    analyzer, t = make(), Thresholds(low=0.4, high=0.7)
    decisions = [decide(analyzer.analyze(IMAGE, meta(i)).score, t) for i in range(400)]
    assert decisions.count(Decision.CONFORME) / len(decisions) > 0.6
    assert {Decision.A_VERIFIER, Decision.ANOMALIE} <= set(decisions)
