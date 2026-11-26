from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from visionhub.contracts import Decision, Thresholds
from visionhub.production.contracts import (
    AIPrediction,
    CorrectionIn,
    ErrorCode,
    InferenceError,
    Part,
    PartVerdict,
    Shift,
    ShiftStart,
)
from visionhub.production.verdicts import verdict_from_decision

NOW = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


def prediction(verdict=PartVerdict.OK, decision=Decision.CONFORME) -> AIPrediction:
    return AIPrediction(
        verdict=verdict,
        ai_decision=decision,
        score=0.1,
        model_name="fake-quality",
        model_version="0.1.0",
        thresholds_used=Thresholds(low=0.4, high=0.7),
        event_id="e1",
        latency_ms=1.0,
    )


def part(**overrides) -> dict:
    data = dict(
        part_id="p1",
        station_id="WS-01",
        cycle_id="C-000001",
        shift_id=None,
        created_at=NOW,
        trigger_source="plc_simulated",
        camera_id="CAM-Q",
        image_sha256=None,
        predicted_verdict=PartVerdict.OK,
        prediction=prediction(),
        error=None,
        effective_verdict=PartVerdict.OK,
        correction_count=0,
    )
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("decision", "verdict"),
    [
        (Decision.CONFORME, PartVerdict.OK),
        (Decision.ANOMALIE, PartVerdict.NOK),
        (Decision.A_VERIFIER, PartVerdict.HOLD),
    ],
)
def test_decision_mapping(decision, verdict):
    assert verdict_from_decision(decision) == verdict


def test_valid_parts():
    Part(**part())
    error = InferenceError(code=ErrorCode.ANALYZER_FAILED, message="boom")
    Part(**part(predicted_verdict="ERROR", prediction=None, error=error, effective_verdict="ERROR"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"predicted_verdict": "ERROR"},  # ERROR with a prediction
        {"prediction": None},  # OK without prediction
        {"error": {"code": "ANALYZER_FAILED", "message": "x"}},  # OK with an error
        {"predicted_verdict": "NOK"},  # mismatch with prediction.verdict
        {"station_id": "bad id with spaces"},
        {"cycle_id": ""},
        {"face_crop": "nope"},  # extra fields are forbidden
    ],
)
def test_invalid_parts(overrides):
    with pytest.raises(ValidationError):
        Part(**part(**overrides))


def test_prediction_cannot_be_error():
    with pytest.raises(ValidationError):
        prediction(verdict=PartVerdict.ERROR)


def test_correction_targets_and_reason():
    base = dict(expected_current_verdict="NOK", reason="checked by hand", actor_role="operator")
    CorrectionIn(new_verdict="OK", **base)
    CorrectionIn(new_verdict="NOK", **{**base, "expected_current_verdict": "OK"})
    for bad in ("HOLD", "ERROR"):
        with pytest.raises(ValidationError):
            CorrectionIn(new_verdict=bad, **base)
    with pytest.raises(ValidationError):
        CorrectionIn(new_verdict="OK", **{**base, "reason": "  "[:1]})
    with pytest.raises(ValidationError):
        CorrectionIn(new_verdict="OK", **{**base, "actor_role": "Jean Dupont"})
    with pytest.raises(ValidationError):
        CorrectionIn(new_verdict="OK", badge_id="1234", **base)


def test_shift_contracts():
    with pytest.raises(ValidationError):
        ShiftStart(name="matin", target_parts=-1)
    with pytest.raises(ValidationError):
        ShiftStart(name="matin", target_parts=10, planned_duration_min=0)
    shift = Shift(
        shift_id="s1",
        station_id="WS-01",
        name="matin",
        status="OPEN",
        started_at=NOW,
        planned_duration_min=480,
        target_parts=100,
    )
    assert shift.planned_end_at == datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
    assert "planned_end_at" in shift.model_dump(mode="json")
    # Our own JSON is accepted back (Edge -> Core); an inconsistent end is rejected.
    assert Shift.model_validate_json(shift.model_dump_json()) == shift
    tampered = {**shift.model_dump(mode="json"), "planned_end_at": "2026-01-01T15:00:00Z"}
    with pytest.raises(ValidationError):
        Shift.model_validate(tampered)
