import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from visionhub.contracts import (
    Decision,
    Event,
    FrameMeta,
    QualityDetails,
    Thresholds,
    UseCase,
)
from visionhub.production.contracts import (
    AIPrediction,
    CorrectionIn,
    DispositionIn,
    ErrorCode,
    InferenceError,
    Part,
    PartVerdict,
    Shift,
)
from visionhub.production.db import MIGRATIONS
from visionhub.production.store import (
    ConflictError,
    DuplicateCycleError,
    InvalidOperationError,
    NotFoundError,
    ProductionStore,
)
from visionhub.store import EventStore

T0 = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)


def make_event(event_id: str, cycle: str = "C1") -> Event:
    return Event(
        use_case=UseCase.QUALITY,
        score=0.9,
        latency_ms=3.0,
        model_name="fake-quality",
        model_version="0.1.0",
        details=QualityDetails(),
        event_id=event_id,
        frame=FrameMeta(frame_id=f"cycle:WS-01:{cycle}", workstation_id="WS-01", camera_id="CAM-Q"),
        decision=Decision.ANOMALIE,
        thresholds_used=Thresholds(low=0.4, high=0.7),
    )


def make_part(cycle: str = "C1", verdict: str = "NOK", shift_id=None, at=T0) -> tuple[Part, Event]:
    if verdict == "ERROR":
        error = InferenceError(code=ErrorCode.ANALYZER_FAILED, message="boom")
        part = Part(
            part_id=str(uuid.uuid4()),
            station_id="WS-01",
            cycle_id=cycle,
            shift_id=shift_id,
            created_at=at,
            trigger_source="plc_simulated",
            camera_id="CAM-Q",
            image_sha256="abc",
            predicted_verdict="ERROR",
            prediction=None,
            error=error,
            effective_verdict="ERROR",
            correction_count=0,
        )
        return part, None
    event = make_event(str(uuid.uuid4()), cycle)
    decision = {"OK": Decision.CONFORME, "NOK": Decision.ANOMALIE, "HOLD": Decision.A_VERIFIER}
    prediction = AIPrediction(
        verdict=verdict,
        ai_decision=decision[verdict],
        score=0.9,
        model_name="fake-quality",
        model_version="0.1.0",
        thresholds_used=Thresholds(low=0.4, high=0.7),
        event_id=event.event_id,
        latency_ms=3.0,
    )
    part = Part(
        part_id=str(uuid.uuid4()),
        station_id="WS-01",
        cycle_id=cycle,
        shift_id=shift_id,
        created_at=at,
        trigger_source="plc_simulated",
        camera_id="CAM-Q",
        image_sha256="abc",
        predicted_verdict=verdict,
        prediction=prediction,
        error=None,
        effective_verdict=verdict,
        correction_count=0,
    )
    return part, event


def correction(new, expected, inspected=False) -> CorrectionIn:
    return CorrectionIn(
        new_verdict=new,
        expected_current_verdict=expected,
        reason="checked on the part",
        actor_role="operator",
        physical_inspection=inspected,
    )


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "argos.db")


@pytest.fixture
def store(db_path):
    s = ProductionStore(db_path)
    yield s
    s.close()


# ------------------------------------------------------------------ migrations


def test_fresh_database_is_migrated_once(db_path):
    first = ProductionStore(db_path)
    assert first.migrations_applied == [v for v, _, _ in MIGRATIONS]
    first.close()
    second = ProductionStore(db_path)
    assert second.migrations_applied == []
    second.close()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(
            MIGRATIONS
        )


def test_migration_preserves_existing_events(db_path):
    legacy = EventStore(db_path)
    for i in range(5):
        legacy.add(make_event(f"legacy-{i}"))
    before = [e.model_dump() for e in legacy.list(limit=100)]
    legacy.close()

    ProductionStore(db_path).close()

    legacy = EventStore(db_path)
    assert [e.model_dump() for e in legacy.list(limit=100)] == before
    legacy.close()


# ------------------------------------------------------------------ parts


def test_part_and_event_are_stored_together(store, db_path):
    part, event = make_part()
    store.insert_part(part, event)
    assert store.get_part(part.part_id) == part
    assert store.get_part_by_cycle("WS-01", "C1") == part
    # The event row is readable by the historical EventStore.
    legacy = EventStore(db_path)
    assert legacy.get(event.event_id) == event
    legacy.close()


def test_duplicate_cycle_rolls_back_its_event(store, db_path):
    part, event = make_part()
    store.insert_part(part, event)
    duplicate, duplicate_event = make_part()
    with pytest.raises(DuplicateCycleError):
        store.insert_part(duplicate, duplicate_event)
    legacy = EventStore(db_path)
    assert legacy.get(duplicate_event.event_id) is None  # no orphan inference event
    legacy.close()
    assert len(store.list_parts()) == 1


def test_prediction_is_immutable_and_parts_cannot_be_deleted(store, db_path):
    part, event = make_part()
    store.insert_part(part, event)
    with sqlite3.connect(db_path) as conn:
        for sql in (
            "UPDATE parts SET predicted_verdict = 'OK'",
            "UPDATE parts SET prediction = NULL",
            "UPDATE parts SET cycle_id = 'other'",
            "DELETE FROM parts",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


def test_list_parts_filters(store):
    for i, verdict in enumerate(["OK", "NOK", "OK", "ERROR"]):
        store.insert_part(*make_part(f"C{i}", verdict, at=T0 + timedelta(seconds=i)))
    assert [p.cycle_id for p in store.list_parts()] == ["C3", "C2", "C1", "C0"]
    assert len(store.list_parts(verdict=PartVerdict.OK)) == 2
    assert store.list_parts(station_id="WS-99") == []
    assert len(store.list_parts(limit=1)) == 1


def test_disposition_is_independent_from_verdict(store):
    part, event = make_part()
    store.insert_part(part, event)
    updated = store.set_disposition(
        part.part_id, DispositionIn(disposition="QUARANTINED", note="bac rouge"), T0
    )
    assert updated.disposition == "QUARANTINED" and updated.disposition_note == "bac rouge"
    assert updated.effective_verdict == PartVerdict.NOK
    with pytest.raises(NotFoundError):
        store.set_disposition("nope", DispositionIn(disposition="SHIPPED"), T0)


# ------------------------------------------------------------------ corrections


def test_correction_keeps_prediction_and_history(store, db_path):
    part, event = make_part(verdict="NOK")
    store.insert_part(part, event)
    updated, first = store.add_correction(part.part_id, correction("OK", "NOK"), "c1", T0)
    assert updated.effective_verdict == PartVerdict.OK
    assert updated.predicted_verdict == PartVerdict.NOK
    assert updated.prediction == part.prediction
    assert updated.correction_count == 1 and first.sequence == 1
    assert first.previous_verdict == PartVerdict.NOK

    updated, second = store.add_correction(part.part_id, correction("NOK", "OK"), "c2", T0)
    assert updated.effective_verdict == PartVerdict.NOK and second.sequence == 2
    assert [c.correction_id for c in store.list_corrections(part.part_id)] == ["c1", "c2"]

    with sqlite3.connect(db_path) as conn:
        for sql in ("UPDATE corrections SET reason = 'x'", "DELETE FROM corrections"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


def test_correction_rules(store):
    part, event = make_part(verdict="NOK")
    store.insert_part(part, event)
    with pytest.raises(ConflictError):  # stale view of the part
        store.add_correction(part.part_id, correction("OK", "OK"), "x", T0)
    with pytest.raises(InvalidOperationError):  # no-op correction
        store.add_correction(part.part_id, correction("NOK", "NOK"), "x", T0)
    with pytest.raises(NotFoundError):
        store.add_correction("nope", correction("OK", "NOK"), "x", T0)
    with pytest.raises(NotFoundError):
        store.list_corrections("nope")
    assert store.list_corrections(part.part_id) == []


@pytest.mark.parametrize("verdict", ["HOLD", "ERROR"])
def test_hold_and_error_need_physical_inspection(store, verdict):
    part, event = make_part(verdict=verdict)
    store.insert_part(part, event)
    with pytest.raises(InvalidOperationError):
        store.add_correction(part.part_id, correction("OK", verdict), "x", T0)
    updated, _ = store.add_correction(part.part_id, correction("NOK", verdict, True), "c", T0)
    assert updated.effective_verdict == PartVerdict.NOK
    assert updated.predicted_verdict == verdict
    if verdict == "ERROR":
        assert updated.error == part.error  # the initial error is kept


def test_concurrent_corrections_lose_nothing(store):
    part, event = make_part(verdict="NOK")
    store.insert_part(part, event)
    outcomes = []

    def attempt(i):
        try:
            store.add_correction(part.part_id, correction("OK", "NOK"), f"c{i}", T0)
            outcomes.append("ok")
        except ConflictError:
            outcomes.append("conflict")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict"] * 7 + ["ok"]
    assert len(store.list_corrections(part.part_id)) == 1
    assert store.get_part(part.part_id).correction_count == 1


# ------------------------------------------------------------------ shifts and tally


def shift(shift_id="s1", station="WS-01") -> Shift:
    return Shift(
        shift_id=shift_id,
        station_id=station,
        name="matin",
        status="OPEN",
        started_at=T0,
        planned_duration_min=480,
        target_parts=100,
    )


def test_one_open_shift_per_station(store):
    store.insert_shift(shift("s1"))
    with pytest.raises(ConflictError):
        store.insert_shift(shift("s2"))
    store.insert_shift(shift("s3", station="WS-02"))
    assert store.current_shift("WS-01").shift_id == "s1"

    closed = store.close_shift("s1", T0 + timedelta(hours=8))
    assert closed.status == "CLOSED" and closed.ended_at == T0 + timedelta(hours=8)
    assert store.current_shift("WS-01") is None
    with pytest.raises(ConflictError):
        store.close_shift("s1", T0)
    with pytest.raises(NotFoundError):
        store.close_shift("nope", T0)
    store.insert_shift(shift("s4"))  # a new shift can open after closing
    assert [s.shift_id for s in store.list_shifts("WS-01")] == ["s4", "s1"]


def test_tally(store):
    store.insert_shift(shift("s1"))
    for i, verdict in enumerate(["OK", "OK", "NOK", "HOLD", "ERROR"]):
        store.insert_part(*make_part(f"C{i}", verdict, shift_id="s1"))
    nok = store.list_parts(verdict=PartVerdict.NOK)[0]
    store.add_correction(nok.part_id, correction("OK", "NOK"), "c1", T0)

    tally = store.tally(shift_id="s1")
    assert tally.total == 5
    assert tally.effective == {PartVerdict.OK: 3, PartVerdict.HOLD: 1, PartVerdict.ERROR: 1}
    assert tally.predicted[PartVerdict.NOK] == 1
    assert tally.corrected == 1
    assert tally.mean_latency_ms == pytest.approx(3.0)
    assert store.tally(shift_id="other").total == 0
    assert store.tally(start=T0 + timedelta(seconds=1)).total == 0
