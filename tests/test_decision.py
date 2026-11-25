import pytest
from pydantic import ValidationError

from visionhub.contracts import (
    AnalysisResult,
    Decision,
    FrameMeta,
    QualityDetails,
    SafetyDetails,
    Thresholds,
    UseCase,
)
from visionhub.decision import decide, to_event

T = Thresholds(low=0.4, high=0.7)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Decision.CONFORME),
        (0.39, Decision.CONFORME),
        (0.4, Decision.A_VERIFIER),
        (0.69, Decision.A_VERIFIER),
        (0.7, Decision.ANOMALIE),
        (1.0, Decision.ANOMALIE),
    ],
)
def test_decide_three_levels(score, expected):
    assert decide(score, T) == expected


def test_equal_thresholds_disable_review_band():
    t = Thresholds(low=0.5, high=0.5)
    assert decide(0.49, t) == Decision.CONFORME
    assert decide(0.5, t) == Decision.ANOMALIE


def test_thresholds_validation():
    with pytest.raises(ValidationError):
        Thresholds(low=0.8, high=0.2)
    with pytest.raises(ValidationError):
        Thresholds(low=-0.1, high=0.5)


def test_details_must_match_use_case():
    with pytest.raises(ValidationError):
        AnalysisResult(
            use_case=UseCase.QUALITY,
            score=0.1,
            model_name="m",
            model_version="1",
            details=SafetyDetails(person_count=0),
        )


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        QualityDetails(zones=[], face_crop="...")


def test_to_event_keeps_result_and_adds_decision():
    meta = FrameMeta(frame_id="f1", workstation_id="WS", camera_id="C")
    result = AnalysisResult(
        use_case=UseCase.QUALITY,
        score=0.5,
        latency_ms=12.0,
        model_name="m",
        model_version="1",
        details=QualityDetails(),
    )
    event = to_event(result, meta, T)
    assert event.decision == Decision.A_VERIFIER
    assert event.thresholds_used == T
    assert event.frame == meta
    assert event.latency_ms == 12.0
    assert event.operator_feedback is None
    # JSON round-trip (what the API and the store do)
    assert type(event).model_validate_json(event.model_dump_json()) == event
