"""Common decision layer: the same rule for every use case.

    score <  low          -> conforme
    low <= score < high   -> a_verifier   (a human checks it)
    score >= high         -> anomalie
"""

from __future__ import annotations

import uuid

from visionhub.contracts import AnalysisResult, Decision, Event, FrameMeta, Thresholds


def decide(score: float, thresholds: Thresholds) -> Decision:
    if score < thresholds.low:
        return Decision.CONFORME
    if score < thresholds.high:
        return Decision.A_VERIFIER
    return Decision.ANOMALIE


def to_event(result: AnalysisResult, meta: FrameMeta, thresholds: Thresholds) -> Event:
    """Apply the decision layer to an analyzer output and build the stored event."""
    return Event(
        **result.model_dump(),
        event_id=str(uuid.uuid4()),
        frame=meta,
        decision=decide(result.score, thresholds),
        thresholds_used=thresholds,
    )
