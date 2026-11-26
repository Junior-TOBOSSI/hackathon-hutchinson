"""A safety Analyzer that composes a PPE detector and a Behavior detector.

Enable it (team decision) in ``usecases/safety/config.yaml``:

    analyzer_class: visionhub.integration.safety_composite:CompositeSafetyAnalyzer
    params:
      ppe:      {detector_class: "usecases.safety.ppe.detector:PPEDetector", ...}
      behavior: {detector_class: "usecases.safety.behavior.detector:BehaviorDetector", ...}

Each section may be omitted: a missing detector contributes nothing (score 0, no person).
The mock detectors below let the composition run before the real models exist.

Fusion rules:
- score = max(PPE score, Behavior score)   (higher = worse, both in [0, 1]);
- persons come from the PPE detector; a ``phone_use`` finding sets ``phone=True`` on the
  matching person_index;
- shoes, earphones, zones and other behaviors are not representable in ``SafetyDetails``
  yet: they only raise the score (see vision.py).
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from visionhub.analyzer import Analyzer
from visionhub.contracts import (
    AnalysisResult,
    FrameMeta,
    PersonPPE,
    PPEState,
    SafetyDetails,
    UseCase,
)
from visionhub.integration.vision import (
    BehaviorDetector,
    BehaviorFinding,
    BehaviorReport,
    PersonPPEExtension,
    PPEDetector,
    PPEReport,
)
from visionhub.registry import import_class


def _build(section: dict[str, Any] | None, device: str, protocol: type):
    if not section:
        return None
    detector = import_class(section["detector_class"])()
    if not isinstance(detector, protocol):
        raise TypeError(f"{section['detector_class']} does not implement {protocol.__name__}")
    detector.load({**section.get("params", {}), "device": device})
    return detector


class CompositeSafetyAnalyzer(Analyzer):
    use_case = UseCase.SAFETY
    name = "argos-safety-composite"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        device = config.get("device", "cpu")
        self.ppe: PPEDetector | None = _build(config.get("ppe"), device, PPEDetector)
        self.behavior: BehaviorDetector | None = _build(
            config.get("behavior"), device, BehaviorDetector
        )

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        ppe = self.ppe.detect(image, meta) if self.ppe else PPEReport(score=0.0)
        behavior = self.behavior.detect(image, meta) if self.behavior else BehaviorReport(score=0.0)
        phone_persons = {
            f.person_index
            for f in behavior.findings
            if f.kind == "phone_use" and f.person_index is not None
        }
        persons = [
            p.model_copy(update={"phone": p.phone or p.person_index in phone_persons})
            for p in ppe.persons
        ]
        return AnalysisResult(
            use_case=self.use_case,
            score=max(ppe.score, behavior.score),
            model_name=self.model_name(),
            model_version=self.model_version(),
            details=SafetyDetails(person_count=len(persons), persons=persons),
        )

    def model_name(self) -> str:
        parts = [d.name for d in (self.ppe, self.behavior) if d]
        return "+".join(parts) or self.name

    def model_version(self) -> str:
        parts = [d.version for d in (self.ppe, self.behavior) if d]
        return "+".join(parts) or self.version


# --------------------------------------------------------------------------- mocks


class MockPPEDetector:
    """Deterministic fake PPE detector (seeded by frame_id). Ignores the pixels."""

    name = "mock-ppe"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.seed = int(config.get("seed", 0))

    def detect(self, image: np.ndarray, meta: FrameMeta) -> PPEReport:
        rng = random.Random(f"{self.seed}-ppe-{meta.frame_id}")
        persons, extensions, worst = [], [], 0.0
        for i in range(rng.randint(0, 2)):
            states = {
                k: rng.choices(list(PPEState), weights=(8, 1, 1))[0]
                for k in ("helmet", "vest", "glasses", "gloves")
            }
            persons.append(PersonPPE(person_index=i, bbox=None, phone=False, **states))
            shoes = rng.choices(list(PPEState), weights=(8, 1, 1))[0]
            extensions.append(PersonPPEExtension(person_index=i, safety_shoes=shoes))
            missing = sum(s == PPEState.ABSENT for s in (*states.values(), shoes))
            uncertain = sum(s == PPEState.UNCERTAIN for s in (*states.values(), shoes))
            worst = max(worst, min(1.0, 0.45 * missing + 0.15 * uncertain))
        return PPEReport(persons=persons, extensions=extensions, score=worst)


class MockBehaviorDetector:
    """Deterministic fake Behavior detector (seeded by frame_id). Ignores the pixels."""

    name = "mock-behavior"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.seed = int(config.get("seed", 0))
        self.rate = float(config.get("finding_rate", 0.1))

    def detect(self, image: np.ndarray, meta: FrameMeta) -> BehaviorReport:
        rng = random.Random(f"{self.seed}-behavior-{meta.frame_id}")
        findings = []
        if rng.random() < self.rate:
            kind = rng.choice(["phone_use", "hand_in_danger_zone", "earphones", "clutter"])
            findings.append(
                BehaviorFinding(
                    kind=kind,
                    confidence=rng.uniform(0.5, 1.0),
                    person_index=0 if kind != "clutter" else None,
                    zone_id="press-1" if kind == "hand_in_danger_zone" else None,
                )
            )
        score = max((f.confidence for f in findings), default=rng.uniform(0.0, 0.2))
        return BehaviorReport(findings=findings, score=score)
