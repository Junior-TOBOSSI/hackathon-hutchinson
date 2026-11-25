"""Tests specific to the safety use case. Adapt them when the real model arrives."""

import numpy as np

from usecases.safety.analyzer import FakeSafetyAnalyzer
from visionhub.contracts import Decision, FrameMeta, PersonPPE, PPEState, Thresholds
from visionhub.decision import decide

IMAGE = np.zeros((240, 320, 3), dtype=np.uint8)
PPE = ("helmet", "vest", "glasses", "gloves")


def make(seed=123):
    analyzer = FakeSafetyAnalyzer()
    analyzer.load({"seed": seed, "max_persons": 3, "device": "cpu"})
    return analyzer


def meta(i):
    return FrameMeta(frame_id=str(i), workstation_id="WS", camera_id="C")


def test_person_count_matches_persons():
    analyzer = make()
    for i in range(100):
        d = analyzer.analyze(IMAGE, meta(i)).details
        assert d.person_count == len(d.persons)


def test_high_score_means_missing_ppe_or_phone():
    analyzer = make()
    for i in range(300):
        r = analyzer.analyze(IMAGE, meta(i))
        if r.score >= 0.7:
            assert any(
                p.phone or any(getattr(p, item) == PPEState.ABSENT for item in PPE)
                for p in r.details.persons
            )


def test_no_identity_fields_in_contract():
    """Privacy by design: a person is only described by position and PPE states."""
    assert set(PersonPPE.model_fields) == {
        "person_index",
        "bbox",
        "helmet",
        "vest",
        "glasses",
        "gloves",
        "phone",
    }


def test_mostly_conforming_with_all_three_decisions():
    analyzer, t = make(), Thresholds(low=0.4, high=0.7)
    decisions = [decide(analyzer.analyze(IMAGE, meta(i)).score, t) for i in range(400)]
    assert decisions.count(Decision.CONFORME) / len(decisions) > 0.6
    assert {Decision.A_VERIFIER, Decision.ANOMALIE} <= set(decisions)
