"""Production KPI rules. Pure functions: no database, no clock.

- Counts use the effective verdict; HOLD and ERROR are never counted as OK nor NOK.
- Every rate whose denominator is 0 is None (no data is not the same as 0 %).
- Hourly rates are None below MIN_ELAPSED_S, where they would be meaningless.
- ``nok_rate`` is NOT a scrap rate: physical scrap is a disposition, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from visionhub.production.contracts import PartVerdict, ProductionKPI

MIN_ELAPSED_S = 60.0


@dataclass
class Tally:
    """Raw counts of a set of parts, as read from the store."""

    effective: dict[PartVerdict, int] = field(default_factory=dict)
    predicted: dict[PartVerdict, int] = field(default_factory=dict)
    corrected: int = 0
    mean_latency_ms: float | None = None

    @property
    def total(self) -> int:
        return sum(self.effective.values())


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def compute_kpi(
    tally: Tally,
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    target_parts: int | None = None,
    planned_duration_min: int | None = None,
) -> ProductionKPI:
    """KPIs over [window_start, min(window_end, now)].

    For a shift, ``window_end`` is ``ended_at`` (closed) or ``now`` (open): a correction
    made after closing changes the counts, never the period.
    """
    end = min(window_end, now)
    elapsed_s = max(0.0, (end - window_start).total_seconds())
    hours = elapsed_s / 3600
    long_enough = elapsed_s >= MIN_ELAPSED_S

    def count(verdicts: dict[PartVerdict, int], verdict: PartVerdict) -> int:
        return verdicts.get(verdict, 0)

    total = tally.total
    ok = count(tally.effective, PartVerdict.OK)
    nok = count(tally.effective, PartVerdict.NOK)
    hold = count(tally.effective, PartVerdict.HOLD)
    error = count(tally.effective, PartVerdict.ERROR)

    expected_ok_rate = None
    expected_by_now = None
    if target_parts is not None and planned_duration_min:
        expected_ok_rate = target_parts / (planned_duration_min / 60)
        expected_by_now = min(float(target_parts), expected_ok_rate * hours)

    return ProductionKPI(
        window_start=window_start,
        window_end=end,
        elapsed_s=elapsed_s,
        total_parts=total,
        ok_parts=ok,
        nok_parts=nok,
        hold_parts=hold,
        error_parts=error,
        predicted_ok_parts=count(tally.predicted, PartVerdict.OK),
        predicted_nok_parts=count(tally.predicted, PartVerdict.NOK),
        predicted_hold_parts=count(tally.predicted, PartVerdict.HOLD),
        predicted_error_parts=count(tally.predicted, PartVerdict.ERROR),
        corrected_parts=tally.corrected,
        yield_rate=ratio(ok, total),
        nok_rate=ratio(nok, total),
        pending_rate=ratio(hold + error, total),
        correction_rate=ratio(tally.corrected, total),
        target_parts=target_parts,
        target_progress=ratio(ok, target_parts) if target_parts is not None else None,
        actual_total_rate_per_hour=total / hours if long_enough else None,
        actual_ok_rate_per_hour=ok / hours if long_enough else None,
        expected_ok_rate_per_hour=expected_ok_rate,
        expected_ok_parts_by_now=expected_by_now,
        efficiency=ratio(ok, expected_by_now) if expected_by_now is not None else None,
        mean_latency_ms=tally.mean_latency_ms,
    )
