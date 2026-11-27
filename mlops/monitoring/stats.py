"""Statistics of the monitoring (pure functions, documented conventions).

PSI (Population Stability Index), conventions used here:
- bins are fixed ONCE from the reference (quantile edges, outer edges open: -inf / +inf)
  and the SAME edges are applied to the monitored population;
- empty bins: both proportions are floored at ``EPSILON`` (1e-4) before the log ratio;
- thresholds are heuristic conventions, not statistical tests: < 0.1 stable,
  0.1 - 0.2 watch, >= 0.2 alert (configurable).
KS: two-sample Kolmogorov-Smirnov on the RAW observations (scipy, exact or asymptotic
p-value as chosen by scipy; reported in ``method_detail``).
Chi-square: only when every expected count is >= 5 (otherwise "not applicable").
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EPSILON = 1e-4


@dataclass(frozen=True)
class Thresholds:
    psi_watch: float = 0.1
    psi_alert: float = 0.2
    min_reference: int = 100
    min_current: int = 100
    latency_shift_ratio: float = 0.5  # +50 % mean latency = alert


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


def reference_edges(reference: Sequence[float], bins: int = 10) -> list[float]:
    """Quantile edges of the reference (duplicates removed), outer edges open."""
    inner = sorted({quantile(reference, i / bins) for i in range(1, bins)})
    return [-math.inf, *inner, math.inf]


def histogram(values: Sequence[float], edges: Sequence[float]) -> list[int]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        for i in range(len(edges) - 1):
            if edges[i] < v <= edges[i + 1] or (i == 0 and v <= edges[1]):
                counts[i] += 1
                break
    return counts


def psi_from_counts(ref_counts: Sequence[int], cur_counts: Sequence[int]) -> float:
    rt, ct = sum(ref_counts), sum(cur_counts)
    total = 0.0
    for r, c in zip(ref_counts, cur_counts, strict=True):
        rp, cp = max(r / rt, EPSILON), max(c / ct, EPSILON)
        total += (cp - rp) * math.log(cp / rp)
    return total


def psi(
    reference: Sequence[float], current: Sequence[float], edges: Sequence[float] | None = None
) -> float:
    edges = list(edges) if edges is not None else reference_edges(reference)
    return psi_from_counts(histogram(reference, edges), histogram(current, edges))


def categorical_psi(reference: dict[str, int], current: dict[str, int]) -> float:
    keys = sorted(set(reference) | set(current))
    return psi_from_counts([reference.get(k, 0) for k in keys], [current.get(k, 0) for k in keys])


def ks(reference: Sequence[float], current: Sequence[float]) -> dict:
    from scipy.stats import ks_2samp

    res = ks_2samp(list(reference), list(current))
    return {
        "statistic": float(res.statistic),
        "p_value": float(res.pvalue),
        "method_detail": "scipy ks_2samp (raw observations)",
    }


def chi2(reference: dict[str, int], current: dict[str, int]) -> dict:
    """Chi-square homogeneity test on decision counts; refused when an expected count < 5."""
    keys = sorted(set(reference) | set(current))
    table = [[reference.get(k, 0) for k in keys], [current.get(k, 0) for k in keys]]
    totals = [sum(r) for r in table]
    cols = [table[0][j] + table[1][j] for j in range(len(keys))]
    grand = sum(totals)
    if grand == 0 or any(c == 0 for c in cols):
        return {"applicable": False, "reason": "empty category"}
    expected = [[totals[i] * cols[j] / grand for j in range(len(keys))] for i in range(2)]
    if min(min(r) for r in expected) < 5:
        return {"applicable": False, "reason": "expected count < 5"}
    from scipy.stats import chi2_contingency

    stat, p, dof, _ = chi2_contingency(table)
    return {"applicable": True, "statistic": float(stat), "p_value": float(p), "dof": int(dof)}


def level(value: float | None, t: Thresholds) -> str:
    if value is None:
        return "unavailable"
    return "alert" if value >= t.psi_alert else "watch" if value >= t.psi_watch else "stable"
