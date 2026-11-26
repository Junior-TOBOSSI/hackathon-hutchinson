from datetime import UTC, datetime, timedelta

import pytest

from visionhub.contracts import Thresholds, UseCase
from visionhub.production.contracts import CorrectionIn, PartVerdict, ShiftStart
from visionhub.production.engine import CycleRequest
from visionhub.production.kpi import Tally, compute_kpi

T0 = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)  # a night shift, crossing midnight
V = PartVerdict


def kpi(tally, hours, **kwargs):
    return compute_kpi(
        tally,
        window_start=T0,
        window_end=T0 + timedelta(hours=hours),
        now=T0 + timedelta(hours=hours),
        **kwargs,
    )


def test_empty_window_has_no_rates():
    k = kpi(Tally(), 0, target_parts=0, planned_duration_min=480)
    assert k.total_parts == 0
    for rate in (
        k.yield_rate,
        k.nok_rate,
        k.pending_rate,
        k.correction_rate,
        k.target_progress,
        k.actual_total_rate_per_hour,
        k.actual_ok_rate_per_hour,
        k.efficiency,
        k.mean_latency_ms,
    ):
        assert rate is None
    assert k.expected_ok_rate_per_hour == 0 and k.expected_ok_parts_by_now == 0


def test_counts_and_rates():
    tally = Tally(
        effective={V.OK: 60, V.NOK: 20, V.HOLD: 10, V.ERROR: 10},
        predicted={V.OK: 55, V.NOK: 25, V.HOLD: 10, V.ERROR: 10},
        corrected=5,
        mean_latency_ms=4.0,
    )
    k = kpi(tally, 2, target_parts=400, planned_duration_min=480)
    assert (k.total_parts, k.ok_parts, k.nok_parts, k.hold_parts, k.error_parts) == (
        100,
        60,
        20,
        10,
        10,
    )
    assert k.predicted_nok_parts == 25 and k.corrected_parts == 5
    assert k.yield_rate == 0.6 and k.nok_rate == 0.2 and k.pending_rate == 0.2
    assert k.yield_rate + k.nok_rate + k.pending_rate == pytest.approx(1.0)
    assert k.correction_rate == 0.05
    assert k.target_progress == 60 / 400
    assert k.actual_total_rate_per_hour == 50 and k.actual_ok_rate_per_hour == 30
    assert k.expected_ok_rate_per_hour == 50
    assert k.expected_ok_parts_by_now == 100
    assert k.efficiency == 0.6
    assert k.elapsed_s == 7200 and k.mean_latency_ms == 4.0


def test_hold_and_error_are_never_ok_nor_nok():
    k = kpi(Tally(effective={V.HOLD: 3, V.ERROR: 2}), 1)
    assert k.ok_parts == k.nok_parts == 0
    assert k.yield_rate == 0 and k.nok_rate == 0 and k.pending_rate == 1


def test_short_window_has_no_hourly_rates():
    k = kpi(Tally(effective={V.OK: 3}), 30 / 3600, target_parts=10, planned_duration_min=60)
    assert k.actual_total_rate_per_hour is None and k.actual_ok_rate_per_hour is None
    assert k.expected_ok_parts_by_now == pytest.approx(10 * 30 / 3600)


def test_expected_parts_are_capped_at_target_after_the_planned_end():
    k = kpi(Tally(effective={V.OK: 90}), 10, target_parts=100, planned_duration_min=480)
    assert k.expected_ok_parts_by_now == 100 and k.efficiency == 0.9


def test_window_end_is_capped_at_now():
    k = compute_kpi(
        Tally(effective={V.OK: 1}),
        window_start=T0,
        window_end=T0 + timedelta(hours=8),
        now=T0 + timedelta(hours=1),
    )
    assert k.elapsed_s == 3600 and k.window_end == T0 + timedelta(hours=1)
    assert k.target_progress is None and k.expected_ok_rate_per_hour is None


# ------------------------------------------------------------------ through the engine


def test_correction_after_closing_updates_counts_not_period(make_engine, clock):
    engine = make_engine()
    engine.registry.set_thresholds(UseCase.QUALITY, Thresholds(low=0.0, high=0.0))  # all NOK
    shift = engine.start_shift("WS-01", ShiftStart(name="nuit", target_parts=8))
    for i in range(4):
        clock.advance(minutes=30)
        engine.run_cycle(CycleRequest("WS-01", f"C{i}", "CAM-Q", True))
    clock.advance(minutes=30)
    closed = engine.close_shift(shift.shift_id)
    assert closed.kpi.nok_parts == 4 and closed.kpi.ok_parts == 0
    assert closed.kpi.elapsed_s == 2.5 * 3600

    clock.advance(hours=3)
    part = engine.store.list_parts(shift_id=shift.shift_id)[0]
    engine.correct(
        part.part_id,
        CorrectionIn(
            new_verdict="OK",
            expected_current_verdict="NOK",
            reason="faux rejet",
            actor_role="operator",
        ),
    )
    report = engine.shift_report(shift.shift_id)
    assert report.kpi.ok_parts == 1 and report.kpi.nok_parts == 3
    assert report.kpi.predicted_nok_parts == 4
    assert report.kpi.correction_rate == 0.25
    assert report.kpi.elapsed_s == closed.kpi.elapsed_s  # the period did not move
    assert report.kpi.window_end == closed.shift.ended_at


def test_station_kpi_window(make_engine, clock):
    engine = make_engine()
    start = clock()
    for i in range(3):
        engine.run_cycle(CycleRequest("WS-01", f"C{i}", "CAM-Q", True))
        clock.advance(minutes=10)
    engine.run_cycle(CycleRequest("WS-02", "C0", "CAM-Q", True))
    k = engine.station_kpi("WS-01", start, clock())
    assert k.total_parts == 3 and k.target_parts is None
    assert engine.station_kpi("WS-01", start, start).total_parts == 0
