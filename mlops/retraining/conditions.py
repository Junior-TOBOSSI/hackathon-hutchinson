"""Pure evaluation of the retraining conditions (no I/O: inputs come from the providers).

States: satisfied | not_satisfied | unavailable. An unavailable condition is NEVER treated as
satisfied. Combination:
- no enabled condition -> not eligible (a policy without condition never triggers);
- AND: every enabled condition must be satisfied;
- OR: at least one satisfied, and every REQUIRED enabled condition satisfied.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mlops.retraining.models import Condition, ConditionResult

TRAINING_SPLITS = ("train", "validation")
USABLE_REVIEWS = ("validated", "corrected", "imported")  # imported = labelled by the AI Leader


def _r(c: Condition, state: str, reason: str, **kw: Any) -> ConditionResult:
    return ConditionResult(kind=c.kind, required=c.required, state=state, reason=reason, **kw)


def drift(c: Condition, windows: list[dict] | None) -> ConditionResult:
    """``windows``: one row per DISTINCT daily window evaluated at collection (several
    collections of one window are one row). Only windows with an available, representative
    and compatible reference, sufficient populations and an allowed origin count."""
    p = c.drift
    if windows is None:
        return _r(
            c,
            "unavailable",
            "no inference is linked to this registered model by an exact "
            "package reference: its drift cannot be evaluated",
        )
    usable = [
        w
        for w in windows
        if w.get("status") == "available"
        and w.get("representative")
        and w.get("data_kind") in p.allowed_origins
    ]
    if not usable:
        return _r(
            c,
            "unavailable",
            "no evaluable window: reference absent, not representative, "
            "insufficient populations or origin not allowed",
            evidence={"windows": len(windows)},
        )
    usable.sort(key=lambda w: w["window_day"])
    last = usable[-p.min_windows :]
    levels = ("alert",) if p.min_level == "alert" else ("alert", "watch")
    hit = len(last) == p.min_windows and all(w.get("level") in levels for w in last)
    days = [w["window_day"] for w in last]
    if not hit:
        return _r(
            c,
            "not_satisfied",
            f"drift >= {p.min_level} not observed on {p.min_windows} distinct "
            f"windows in a row (last: {', '.join(days)})",
            evidence={"windows": days},
        )
    simulated = any(w["data_kind"] == "simulated" for w in last)
    return _r(
        c,
        "satisfied",
        f"persistent drift on {p.min_windows} distinct windows ({', '.join(days)})",
        evidence={"windows": days, "references": sorted({w.get("reference_id") for w in last})},
        evidence_key="drift:" + ",".join(days),
        simulated=simulated,
    )


def annotation_diff(trained: list[dict], target: list[dict]) -> dict[str, Any]:
    """New or modified usable annotations of ``target`` versus the dataset version used by
    the last relevant training, by IMAGE identity (sha256): never the whole new version,
    never twice the same image."""
    before = {i["sha256"]: i for i in trained}
    added = modified = validated_only = test_changes = 0
    for i in {x["sha256"]: x for x in target}.values():
        old = before.get(i["sha256"])
        changed = old is None or old.get("label") != i.get("label")
        if not changed:
            validated_only += i.get("review") == "validated"
            continue
        if i.get("split") not in TRAINING_SPLITS:
            test_changes += 1  # changes the evaluation, not the training data
            continue
        if i.get("review") not in USABLE_REVIEWS:
            continue  # unreviewed: not a validated annotation
        added += old is None
        modified += old is not None
    return {
        "added": added,
        "modified": modified,
        "new_usable": added + modified,
        "validated_without_change": validated_only,
        "test_split_changes": test_changes,
    }


def annotations(
    c: Condition,
    trained_version: str | None,
    target_version: str | None,
    diff: dict[str, Any] | None,
) -> ConditionResult:
    if trained_version is None:
        return _r(
            c,
            "unavailable",
            "no previous successful training of this pipeline on this "
            "dataset family: no baseline to count new annotations",
        )
    if target_version is None or diff is None:
        return _r(c, "unavailable", "target dataset version or manifests unavailable")
    ev = {"trained_on": trained_version, "target": target_version, **diff}
    n = diff["new_usable"]
    if n >= c.annotations.min_new:
        return _r(
            c,
            "satisfied",
            f"{n} new or modified validated annotations (train / validation) "
            f"since {trained_version} (threshold {c.annotations.min_new})",
            evidence=ev,
            evidence_key=f"annotations:{trained_version}->{target_version}",
        )
    return _r(
        c,
        "not_satisfied",
        f"{n} new validated annotations since {trained_version} (< {c.annotations.min_new})",
        evidence=ev,
    )


def performance(c: Condition, production: dict | None) -> ConditionResult:
    if production is None:
        return _r(
            c,
            "unavailable",
            "no representative labelled production sample (ground truth): "
            "production performance cannot be measured",
        )
    drop = production.get("drop")
    if drop is not None and drop >= c.performance.max_drop:
        return _r(
            c,
            "satisfied",
            f"{c.performance.metric} dropped by {drop:.3f}",
            evidence=production,
            evidence_key=f"performance:{production.get('window')}",
        )
    return _r(
        c,
        "not_satisfied",
        f"{c.performance.metric} drop below {c.performance.max_drop}",
        evidence=production,
    )


def schedule(c: Condition, last_training: dict | None, now: datetime) -> ConditionResult:
    if not last_training or not last_training.get("started_at"):
        return _r(c, "unavailable", "no previous successful training: the interval has no origin")
    start = datetime.fromisoformat(last_training["started_at"].replace("Z", "+00:00"))
    due = start + timedelta(days=c.schedule.interval_days)
    ev = {
        "last_training": last_training.get("job_run_id"),
        "last_at": start.isoformat(),
        "due": due.isoformat(),
    }
    if now >= due:
        return _r(
            c,
            "satisfied",
            f"{c.schedule.interval_days} days elapsed since the last training",
            evidence=ev,
            evidence_key=f"schedule:{last_training.get('job_run_id')}",
        )
    return _r(c, "not_satisfied", f"next due {due.date().isoformat()}", evidence=ev)


def manual(c: Condition, pending: list[dict]) -> ConditionResult:
    if not pending:
        return _r(c, "not_satisfied", "no pending manual request")
    ids = [p["request_id"] for p in pending]
    return _r(
        c,
        "satisfied",
        f"{len(ids)} manual request(s) by {', '.join(sorted({p['actor'] for p in pending}))}",
        evidence={"requests": ids},
        evidence_key="manual:" + ",".join(ids),
    )


def combine(logic: str, results: list[ConditionResult]) -> tuple[bool, str]:
    if not results:
        return False, "no active condition: this policy never triggers"
    sat = [r for r in results if r.state == "satisfied"]
    if logic == "AND":
        bad = [r for r in results if r.state != "satisfied"]
        if bad:
            return False, "AND: " + "; ".join(f"{r.kind} {r.state}" for r in bad)
        return True, "AND: every active condition is satisfied"
    blocking = [r for r in results if r.required and r.state != "satisfied"]
    if blocking:
        return False, "OR: required condition(s) " + "; ".join(
            f"{r.kind} {r.state}" for r in blocking
        )
    if not sat:
        return False, "OR: no active condition is satisfied"
    return True, "OR: " + ", ".join(r.kind for r in sat) + " satisfied"
