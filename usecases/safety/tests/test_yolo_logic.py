"""Business rules of the YOLO safety analyzer, tested with simulated detections (no model)."""

from collections import deque

import numpy as np

from usecases.safety.yolo_analyzer import (
    DEFAULTS,
    Det,
    YoloSafetyAnalyzer,
    assess_frame,
    assess_person,
)
from visionhub.contracts import Decision, FrameMeta, PPEState, Thresholds
from visionhub.decision import decide

P = dict(DEFAULTS)
PERSON = Det("person", 0.9, (0.30, 0.05, 0.60, 0.99))  # cut at the bottom: feet not in view
FULL_BODY = Det("person", 0.9, (0.30, 0.05, 0.60, 0.90))  # feet in view
THRESHOLDS = Thresholds(low=0.4, high=0.7)


def states(parts, person=PERSON, phones=()):
    return assess_person(person, list(parts), list(phones), P)


def test_nothing_visible_is_uncertain_not_absent():
    a = states([])
    assert all(a.states[i] == PPEState.UNCERTAIN for i in ("helmet", "glasses", "gloves", "shoes"))
    assert a.evidence == {}


def test_bare_hand_means_gloves_absent():
    a = states([Det("hands", 0.8, (0.32, 0.5, 0.36, 0.55))])
    assert a.states["gloves"] == PPEState.ABSENT


def test_one_bare_hand_is_enough_even_with_one_glove():
    a = states(
        [Det("gloves", 0.9, (0.32, 0.5, 0.36, 0.55)), Det("hands", 0.7, (0.5, 0.5, 0.54, 0.55))]
    )
    assert a.states["gloves"] == PPEState.ABSENT


def test_gloves_only_means_present():
    assert (
        states([Det("gloves", 0.6, (0.32, 0.5, 0.36, 0.55))]).states["gloves"] == PPEState.PRESENT
    )


def test_head_without_helmet_and_face_without_glasses():
    a = states(
        [Det("head", 0.9, (0.4, 0.06, 0.5, 0.16)), Det("face", 0.9, (0.42, 0.09, 0.48, 0.15))]
    )
    assert a.states["helmet"] == PPEState.ABSENT
    assert a.states["glasses"] == PPEState.ABSENT


def test_helmet_and_glasses_present():
    a = states([
        Det("head", 0.9, (0.4, 0.06, 0.5, 0.16)), Det("helmet", 0.8, (0.4, 0.05, 0.5, 0.1)),
        Det("face", 0.9, (0.42, 0.09, 0.48, 0.15)), Det("glasses", 0.7, (0.42, 0.1, 0.48, 0.12)),
    ])  # fmt: skip
    assert a.states["helmet"] == PPEState.PRESENT
    assert a.states["glasses"] == PPEState.PRESENT


def test_shoes_absent_only_when_the_whole_body_is_visible():
    assert states([], person=PERSON).states["shoes"] == PPEState.UNCERTAIN
    full = states([], person=FULL_BODY)
    assert full.states["shoes"] == PPEState.ABSENT
    assert full.evidence["shoes"] == P["shoes_absent_score"]
    shod = states([Det("shoes", 0.5, (0.35, 0.85, 0.4, 0.9))], person=FULL_BODY)
    assert shod.states["shoes"] == PPEState.PRESENT


def test_inferred_missing_shoes_is_a_verifier_not_anomalie():
    _, score = assess_frame([FULL_BODY], [], P)
    assert decide(score, THRESHOLDS) == Decision.A_VERIFIER


def test_phone_in_hand_or_at_the_ear_but_not_on_the_bench():
    hand = Det("hands", 0.8, (0.32, 0.5, 0.36, 0.55))
    head = Det("head", 0.9, (0.4, 0.06, 0.5, 0.16))
    assert states([hand], phones=[Det("cell phone", 0.6, (0.33, 0.48, 0.37, 0.53))]).phone
    assert states([head], phones=[Det("cell phone", 0.6, (0.5, 0.08, 0.53, 0.14))]).phone
    assert not states([hand], phones=[Det("cell phone", 0.6, (0.8, 0.9, 0.85, 0.95))]).phone


def test_strong_evidence_is_anomalie_weak_is_a_verifier():
    strong = [PERSON, Det("hands", 0.9, (0.32, 0.5, 0.36, 0.55))]
    weak = [PERSON, Det("hands", 0.2, (0.32, 0.5, 0.36, 0.55))]
    assert decide(assess_frame(strong, [], P)[1], THRESHOLDS) == Decision.ANOMALIE
    assert decide(assess_frame(weak, [], P)[1], THRESHOLDS) == Decision.A_VERIFIER


def test_non_required_ppe_does_not_raise_the_score():
    dets = [PERSON, Det("hands", 0.9, (0.32, 0.5, 0.36, 0.55))]
    assert assess_frame(dets, [], {**P, "required": ["helmet"]})[1] == 0.0


def test_parts_go_to_the_right_person():
    left = Det("person", 0.9, (0.0, 0.0, 0.4, 0.99))
    right = Det("person", 0.9, (0.6, 0.0, 1.0, 0.99))
    assessed, _ = assess_frame([left, right, Det("hands", 0.9, (0.7, 0.5, 0.75, 0.55))], [], P)
    assert assessed[0].states["gloves"] == PPEState.UNCERTAIN
    assert assessed[1].states["gloves"] == PPEState.ABSENT


def make_analyzer(frames):
    """Analyzer without real models: each call to _predict returns the next simulated frame."""
    analyzer = YoloSafetyAnalyzer()
    analyzer.p, analyzer.device = dict(P), "cpu"
    analyzer.model, analyzer.phone_model = "ppe", None
    analyzer.recent = deque(maxlen=P["smoothing_frames"])
    queue = iter(frames)
    analyzer._predict = lambda model, image, conf, classes=None: next(queue)
    return analyzer


def meta(i):
    return FrameMeta(frame_id=str(i), workstation_id="WS", camera_id="C")


IMAGE = np.zeros((240, 320, 3), dtype=np.uint8)
BARE_HAND = [PERSON, Det("hands", 0.9, (0.32, 0.5, 0.36, 0.55))]
GOOD = [PERSON, Det("gloves", 0.9, (0.32, 0.5, 0.36, 0.55))]


def test_one_bad_frame_does_not_raise_an_alert():
    analyzer = make_analyzer([GOOD, GOOD, BARE_HAND, GOOD])
    scores = [analyzer.analyze(IMAGE, meta(i)).score for i in range(4)]
    assert all(decide(s, THRESHOLDS) == Decision.CONFORME for s in scores)


def test_problem_lasting_three_frames_raises_an_alert():
    analyzer = make_analyzer([BARE_HAND] * 3)
    scores = [analyzer.analyze(IMAGE, meta(i)).score for i in range(3)]
    assert decide(scores[-1], THRESHOLDS) == Decision.ANOMALIE


def test_output_respects_the_contract_and_holds_no_image():
    analyzer = make_analyzer([BARE_HAND])
    result = analyzer.analyze(IMAGE, meta(0))
    person = result.details.persons[0]
    assert result.details.person_count == 1
    assert person.gloves == PPEState.ABSENT
    assert person.vest == PPEState.UNCERTAIN  # not checked at this workstation
    dumped = result.model_dump_json()
    assert "image" not in dumped and "face" not in dumped


def test_no_alert_at_start_up_before_the_window_is_full():
    analyzer = make_analyzer([BARE_HAND] * 3)
    scores = [analyzer.analyze(IMAGE, meta(i)).score for i in range(3)]
    assert scores[0] == 0.0 and scores[1] == 0.0
    assert decide(scores[2], THRESHOLDS) == Decision.ANOMALIE


def test_problem_seen_on_two_frames_out_of_three_still_alerts():
    """A phone or a hand half hidden is often missed on one frame: the alert must stay."""
    analyzer = make_analyzer([BARE_HAND, GOOD, BARE_HAND, BARE_HAND])
    scores = [analyzer.analyze(IMAGE, meta(i)).score for i in range(4)]
    assert decide(scores[2], THRESHOLDS) == Decision.ANOMALIE
    assert decide(scores[3], THRESHOLDS) == Decision.ANOMALIE
