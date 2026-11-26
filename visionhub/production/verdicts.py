"""Mapping from the inference decision layer to industrial part verdicts."""

from __future__ import annotations

from visionhub.contracts import Decision
from visionhub.production.contracts import PartVerdict

DECISION_TO_VERDICT: dict[Decision, PartVerdict] = {
    Decision.CONFORME: PartVerdict.OK,
    Decision.ANOMALIE: PartVerdict.NOK,
    Decision.A_VERIFIER: PartVerdict.HOLD,
}


def verdict_from_decision(decision: Decision) -> PartVerdict:
    """An inference error never goes through here: it is always ERROR, never OK."""
    return DECISION_TO_VERDICT[decision]
