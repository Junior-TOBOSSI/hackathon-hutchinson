"""Interfaces of the PPE and Behavior detectors, and proposed contract extensions.

The safety use case stays ONE analyzer in the registry. PPE and Behavior are two
detectors composed behind it (``safety_composite.CompositeSafetyAnalyzer``), so the
registry, the decision layer and the other use cases are untouched.

``PersonPPEExtension`` and ``BehaviorFinding`` carry what ``SafetyDetails`` cannot hold
yet (shoes, earphones, danger zones, behaviors). They become visible in events only
after the team agrees on the additive extension of ``visionhub/contracts.py`` described
in ``docs/integration-contracts.md``; until then they raise the score but are not stored.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np
from pydantic import Field

from visionhub.contracts import BBox, Contract, FrameMeta, PersonPPE, PPEState, Score

BehaviorKind = Literal[
    # PPE-adjacent behaviors
    "phone_use",
    "earphones",
    # danger zones
    "hand_in_danger_zone",
    "person_in_danger_zone",
    # risky behaviors
    "running",
    "fall",
    "unsafe_posture",
    # 5S / workstation deviations
    "clutter",
    "missing_object",
    "misplaced_object",
    "unexpected_object",
]


class DangerZone(Contract):
    """A polygon in normalized image coordinates, configured per camera."""

    zone_id: str
    polygon: list[tuple[float, float]] = Field(min_length=3)
    kind: Literal["machine", "press", "conveyor", "forklift_lane", "other"] = "machine"


class PersonPPEExtension(Contract):
    """Extra PPE items for one person (same person_index as PersonPPE)."""

    person_index: int = Field(ge=0)
    safety_shoes: PPEState = PPEState.UNCERTAIN
    earphones: bool = False


class PPEReport(Contract):
    persons: list[PersonPPE] = Field(default_factory=list)
    extensions: list[PersonPPEExtension] = Field(default_factory=list)
    score: Score


class BehaviorFinding(Contract):
    kind: BehaviorKind
    confidence: Score
    person_index: int | None = Field(default=None, ge=0, description="Frame index only")
    zone_id: str | None = None
    bbox: BBox | None = None


class BehaviorReport(Contract):
    findings: list[BehaviorFinding] = Field(default_factory=list)
    score: Score


@runtime_checkable
class PPEDetector(Protocol):
    """Implemented by the AI PPE group. Heavy imports go inside load()."""

    name: str
    version: str

    def load(self, config: dict[str, Any]) -> None: ...

    def detect(self, image: np.ndarray, meta: FrameMeta) -> PPEReport: ...


@runtime_checkable
class BehaviorDetector(Protocol):
    """Implemented by the AI Behavior group. Heavy imports go inside load()."""

    name: str
    version: str

    def load(self, config: dict[str, Any]) -> None: ...

    def detect(self, image: np.ndarray, meta: FrameMeta) -> BehaviorReport: ...
