import threading

import cv2
import pytest

from visionhub.contracts import Thresholds, UseCase
from visionhub.production.contracts import (
    CorrectionIn,
    ErrorCode,
    PartVerdict,
    ShiftStart,
)
from visionhub.production.engine import CycleRequest
from visionhub.production.store import ConflictError, InvalidOperationError, NotFoundError
from visionhub.sources import synthetic_frame


def sim(cycle="C-000001", station="WS-01", camera="CAM-Q", image=None, simulated=True):
    return CycleRequest(station, cycle, camera, simulated, image)


def png(index=0) -> bytes:
    ok, buf = cv2.imencode(".png", synthetic_frame(index))
    assert ok
    return buf.tobytes()


def force(engine, low, high):
    engine.registry.set_thresholds(UseCase.QUALITY, Thresholds(low=low, high=high))


# ------------------------------------------------------------------ cycles


def test_cycle_runs_only_the_quality_analyzer(make_engine, spy):
    engine = make_engine()
    calls = {uc: [] for uc in UseCase}
    for uc in UseCase:
        spy(engine.registry.get(uc), calls[uc])

    part, replayed = engine.run_cycle(sim())
    assert not replayed
    assert calls[UseCase.QUALITY] == ["cycle:WS-01:C-000001"]
    assert calls[UseCase.WORKSTATION] == calls[UseCase.SAFETY] == []
    assert part.trigger_source == "plc_simulated"
    # The prediction carries the name of the quality analyzer that is configured
    # (usecases/quality/config.yaml), whichever it is (fake or the real qualite702 model).
    quality = engine.registry.get(UseCase.QUALITY)
    assert part.prediction.model_name == quality.name
    assert part.prediction.model_version == quality.version
    # The inference event is stored and readable by the historical store.
    event = engine.events.get(part.prediction.event_id)
    assert event.frame.frame_id == "cycle:WS-01:C-000001"
    assert event.latency_ms == part.prediction.latency_ms > 0


@pytest.mark.parametrize(
    ("low", "high", "verdict"),
    [(1.0, 1.0, PartVerdict.OK), (0.0, 0.0, PartVerdict.NOK), (0.0, 1.0, PartVerdict.HOLD)],
)
def test_verdict_follows_decision_layer(make_engine, low, high, verdict):
    engine = make_engine()
    force(engine, low, high)
    part, _ = engine.run_cycle(sim())
    assert part.predicted_verdict == part.effective_verdict == verdict
    assert part.prediction.thresholds_used == Thresholds(low=low, high=high)


def test_replay_returns_same_part_without_new_inference(make_engine, spy):
    engine = make_engine()
    calls = []
    spy(engine.registry.get(UseCase.QUALITY), calls)
    first, _ = engine.run_cycle(sim())
    again, replayed = engine.run_cycle(sim())
    assert replayed and again == first
    assert len(calls) == 1
    assert len(engine.store.list_parts()) == 1
    assert len(engine.events.list(limit=100)) == 1


def test_replay_survives_a_restart(make_engine, spy):
    first, _ = make_engine().run_cycle(sim())
    restarted = make_engine()
    calls = []
    spy(restarted.registry.get(UseCase.QUALITY), calls)
    again, replayed = restarted.run_cycle(sim())
    assert replayed and again == first and calls == []


def test_same_cycle_with_other_content_is_a_conflict(make_engine):
    engine = make_engine()
    engine.run_cycle(sim(image=png(0)))
    with pytest.raises(ConflictError):
        engine.run_cycle(sim(image=png(1)))
    with pytest.raises(ConflictError):
        engine.run_cycle(sim(image=png(0), camera="CAM-2"))
    with pytest.raises(ConflictError):
        engine.run_cycle(sim(image=png(0), simulated=False))
    engine.run_cycle(sim(image=png(0)))  # the identical replay is still accepted
    # Same cycle id on another station is another part.
    _, replayed = engine.run_cycle(sim(image=png(1), station="WS-02"))
    assert not replayed


def test_concurrent_triggers_create_one_part_and_one_inference(make_engine, spy):
    engine = make_engine()
    calls = []
    spy(engine.registry.get(UseCase.QUALITY), calls)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(engine.run_cycle(sim()))) for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len({part.part_id for part, _ in results}) == 1
    assert sorted(replayed for _, replayed in results) == [False] + [True] * 9


# ------------------------------------------------------------------ errors


def test_analyzer_exception_gives_a_persisted_error_part(make_engine, spy):
    engine = make_engine()
    force(engine, 1.0, 1.0)  # everything would be OK if the analyzer worked
    spy(engine.registry.get(UseCase.QUALITY), [], raises=RuntimeError("GPU lost"))
    part, _ = engine.run_cycle(sim())
    assert part.predicted_verdict == part.effective_verdict == PartVerdict.ERROR
    assert part.error.code == ErrorCode.ANALYZER_FAILED
    assert part.prediction is None
    assert engine.store.get_part(part.part_id) == part
    assert engine.events.list() == []  # no inference event for a failed inference


def test_quality_not_loaded_gives_error(make_engine):
    engine = make_engine(enabled=[UseCase.WORKSTATION, UseCase.SAFETY])
    part, _ = engine.run_cycle(sim())
    assert part.predicted_verdict == PartVerdict.ERROR
    assert part.error.code == ErrorCode.ANALYZER_UNAVAILABLE


def test_undecodable_image_gives_error(make_engine):
    part, _ = make_engine().run_cycle(sim(image=b"not an image", simulated=False))
    assert part.error.code == ErrorCode.IMAGE_DECODE_FAILED
    assert part.image_sha256 is not None


def test_industrial_cycle_without_image_never_uses_a_synthetic_image(make_engine, spy):
    engine = make_engine()
    calls = []
    spy(engine.registry.get(UseCase.QUALITY), calls)
    part, _ = engine.run_cycle(sim(simulated=False))
    assert part.trigger_source == "plc"
    assert part.predicted_verdict == PartVerdict.ERROR
    assert part.error.code == ErrorCode.CAPTURE_FAILED
    assert calls == []


def test_industrial_cycle_with_image(make_engine):
    part, _ = make_engine().run_cycle(sim(image=png(), simulated=False))
    assert part.trigger_source == "plc" and part.prediction is not None


# ------------------------------------------------------------------ shifts


def test_parts_are_attached_to_the_open_shift(make_engine, clock):
    engine = make_engine()
    before, _ = engine.run_cycle(sim("C0"))
    assert before.shift_id is None
    shift = engine.start_shift("WS-01", ShiftStart(name="matin", target_parts=100))
    during, _ = engine.run_cycle(sim("C1"))
    other_station, _ = engine.run_cycle(sim("C1", station="WS-02"))
    assert during.shift_id == shift.shift_id
    assert other_station.shift_id is None
    clock.advance(hours=8)
    report = engine.close_shift(shift.shift_id)
    assert report.shift.status == "CLOSED" and report.kpi.total_parts == 1
    after, _ = engine.run_cycle(sim("C2"))
    assert after.shift_id is None
    with pytest.raises(ConflictError):
        engine.close_shift(shift.shift_id)
    with pytest.raises(NotFoundError):
        engine.current_shift_report("WS-01")


def test_second_open_shift_is_refused(make_engine):
    engine = make_engine()
    engine.start_shift("WS-01", ShiftStart(name="matin", target_parts=10))
    with pytest.raises(ConflictError):
        engine.start_shift("WS-01", ShiftStart(name="bis", target_parts=10))


# ------------------------------------------------------------------ corrections


def correction(new, expected, inspected=False):
    return CorrectionIn(
        new_verdict=new,
        expected_current_verdict=expected,
        reason="part verified by hand",
        actor_role="operator",
        physical_inspection=inspected,
    )


def test_nok_to_ok_and_back_keeps_the_prediction(make_engine):
    engine = make_engine()
    force(engine, 0.0, 0.0)
    part, _ = engine.run_cycle(sim())
    corrected = engine.correct(part.part_id, correction("OK", "NOK"))
    assert corrected.effective_verdict == PartVerdict.OK
    assert corrected.prediction == part.prediction
    assert corrected.predicted_verdict == PartVerdict.NOK
    back = engine.correct(part.part_id, correction("NOK", "OK"))
    assert back.effective_verdict == PartVerdict.NOK and back.correction_count == 2
    history = engine.store.list_corrections(part.part_id)
    assert [(c.previous_verdict, c.new_verdict) for c in history] == [
        (PartVerdict.NOK, "OK"),
        (PartVerdict.OK, "NOK"),
    ]
    # The original inference event is untouched too.
    assert engine.events.get(part.prediction.event_id).decision == "anomalie"


def test_error_correction_requires_inspection_and_keeps_the_error(make_engine):
    engine = make_engine()
    part, _ = engine.run_cycle(sim(simulated=False))
    with pytest.raises(InvalidOperationError):
        engine.correct(part.part_id, correction("OK", "ERROR"))
    fixed = engine.correct(part.part_id, correction("OK", "ERROR", inspected=True))
    assert fixed.effective_verdict == PartVerdict.OK
    assert fixed.predicted_verdict == PartVerdict.ERROR and fixed.error == part.error


def test_disposition(make_engine):
    from visionhub.production.contracts import DispositionIn

    engine = make_engine()
    part, _ = engine.run_cycle(sim())
    updated = engine.set_disposition(part.part_id, DispositionIn(disposition="SCRAPPED"))
    assert updated.disposition == "SCRAPPED"
    assert updated.effective_verdict == part.effective_verdict
