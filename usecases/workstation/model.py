"""Workstation analyzer: identify the elements of the station and keep some zones empty.

For every image (camera fixed, top view):

1. IDENTIFY: an object detector runs on the WHOLE image. Every detection goes to
   ``details.detected`` (label, confidence, normalized box). Expected elements that are not
   seen go to ``details.missing``.
2. EMPTY ZONES: for each zone that must stay empty (polygon in config.yaml):
   - a detected object whose box overlaps the zone by more than ``min_overlap`` is a
     violation, and we know WHAT it is ("cell phone in keep_clear");
   - pixels that differ from the reference image (the tidy station) reveal ANY object,
     even one the model does not know; such a region, not explained by a detection, is
     reported as ``unknown_object``.
   Violations are written ``"<label>@<zone>"`` in ``details.misplaced``.
3. PERSISTENCE: a problem counts only after ``persistence_frames`` consecutive frames, so a
   hand passing through the zone does not raise an alert.
4. SCORE (in [0, 1], higher = worse): the score of the worst confirmed problem. The common
   decision layer turns it into conforme / a_verifier / anomalie.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from usecases.workstation.detector import REPO_ROOT, Detection, build_detector
from usecases.workstation.zones import (
    Box,
    Polygon,
    box_overlap,
    boxes_mask,
    changed_blobs,
    polygon_mask,
    validate_polygon,
)
from visionhub.analyzer import Analyzer
from visionhub.contracts import (
    AnalysisResult,
    BBox,
    DetectedObject,
    FrameMeta,
    UseCase,
    WorkstationDetails,
)

log = logging.getLogger(__name__)

UNKNOWN = "unknown_object"


class ZoneWorkstationAnalyzer(Analyzer):
    use_case = UseCase.WORKSTATION
    name = "zone-workstation"
    version = "0.1.0"

    # ------------------------------------------------------------------ loading

    def load(self, config: dict[str, Any]) -> None:
        self.detector = build_detector(config)
        self.expected: list[str] = list(config.get("expected_objects") or [])
        self.ignore_labels: set[str] = set(config.get("ignore_labels") or ["person"])
        self.zones: dict[str, Polygon] = {
            name: validate_polygon(name, points)
            for name, points in (config.get("empty_zones") or {}).items()
        }
        self.min_overlap = float(config.get("min_overlap", 0.15))
        self.diff_threshold = float(config.get("diff_threshold", 35))
        self.min_blob_area = float(config.get("min_blob_area", 0.01))
        self.full_blob_area = float(config.get("full_blob_area", 0.05))
        self.persistence_frames = max(1, int(config.get("persistence_frames", 3)))
        self.missing_score = float(config.get("missing_score", 0.5))

        self.reference = self._load_reference(config.get("reference_image"))
        self._masks: dict[tuple[int, int], dict[str, np.ndarray]] = {}
        self._streak: dict[str, int] = {}  # problem key -> consecutive frames seen

    def _load_reference(self, path: str | None) -> np.ndarray | None:
        """Reference image of the tidy station. None -> the first analyzed frame is used."""
        if not path:
            log.info("No reference_image: the first analyzed frame becomes the reference")
            return None
        full = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
        image = cv2.imread(str(full))
        if image is None:
            log.warning("Reference image %s not found: the first frame will be used", full)
        return image

    def reset_reference(self, image: np.ndarray) -> None:
        """Take a new reference (e.g. after the station was rearranged on purpose)."""
        self.reference = image.copy()
        self._streak.clear()

    # ------------------------------------------------------------------ analysis

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        h, w = image.shape[:2]
        if self.reference is None:
            self.reset_reference(image)

        detections = self.detector(image)
        detected = [_to_contract(d.label, d.confidence, d.box, w, h) for d in detections]
        labels = {d.label for d in detections}

        # Candidate problems of THIS frame: key -> (score, contract object or None).
        candidates: dict[str, tuple[float, DetectedObject | None]] = {}
        for label in self.expected:
            if label not in labels:
                candidates[f"missing:{label}"] = (self.missing_score, None)

        objects = [d for d in detections if d.label not in self.ignore_labels]
        # The operator (person boxes) is never judged by the pixel difference.
        ignore = boxes_mask([d.box for d in detections if d.label in self.ignore_labels], (h, w))
        for zone, mask in self._zone_masks((h, w)).items():
            candidates.update(self._zone_problems(zone, mask, image, objects, ignore, w, h))

        confirmed = self._confirm(candidates)

        missing = [k.split(":", 1)[1] for k in confirmed if k.startswith("missing:")]
        misplaced = [k for k in confirmed if not k.startswith("missing:")]
        detected += [obj for k, (_, obj) in confirmed.items() if obj is not None]
        score = max((s for s, _ in confirmed.values()), default=0.0)

        return AnalysisResult(
            use_case=self.use_case,
            score=min(1.0, score),
            model_name=f"{self.name}+{self.detector.name}",
            model_version=self.version,
            details=WorkstationDetails(
                expected=self.expected, detected=detected, missing=missing, misplaced=misplaced
            ),
        )

    def _zone_masks(self, shape: tuple[int, int]) -> dict[str, np.ndarray]:
        """Zone masks for this image size, computed once and cached."""
        if shape not in self._masks:
            self._masks[shape] = {name: polygon_mask(p, shape) for name, p in self.zones.items()}
        return self._masks[shape]

    def _zone_problems(
        self,
        zone: str,
        mask: np.ndarray,
        image: np.ndarray,
        objects: list[Detection],
        ignore: np.ndarray,
        w: int,
        h: int,
    ) -> dict[str, tuple[float, DetectedObject | None]]:
        problems: dict[str, tuple[float, DetectedObject | None]] = {}

        # 1. Known objects: share of the box inside the zone.
        inside = [d for d in objects if box_overlap(d.box, mask) >= self.min_overlap]
        for d in inside:
            key = f"{d.label}@{zone}"
            problems[key] = (max(d.confidence, problems.get(key, (0.0, None))[0]), None)

        # 2. Any object: difference with the reference, restricted to the zone.
        zone_area = max(int(mask.sum()), 1)
        blobs = changed_blobs(
            image,
            self.reference,
            mask,
            diff_threshold=self.diff_threshold,
            min_area=max(1, int(self.min_blob_area * zone_area)),
            ignore_mask=ignore,
        )
        # A blob already explained by a detected object is not reported twice.
        unknown = [b for b in blobs if not any(_contains(d.box, b.center) for d in objects)]
        if unknown:
            biggest = max(unknown, key=lambda b: b.area)
            # Confidence grows with the covered share of the zone (full at full_blob_area).
            confidence = min(1.0, biggest.area / (self.full_blob_area * zone_area))
            obj = _to_contract(UNKNOWN, confidence, biggest.box, w, h)
            problems[f"{UNKNOWN}@{zone}"] = (confidence, obj)
        return problems

    def _confirm(
        self, candidates: dict[str, tuple[float, DetectedObject | None]]
    ) -> dict[str, tuple[float, DetectedObject | None]]:
        """Keep only the problems seen on ``persistence_frames`` consecutive frames."""
        self._streak = {key: self._streak.get(key, 0) + 1 for key in candidates}
        return {k: v for k, v in candidates.items() if self._streak[k] >= self.persistence_frames}


def _contains(box: Box, point: tuple[float, float]) -> bool:
    x1, y1, x2, y2 = box
    x, y = point
    return x1 <= x <= x2 and y1 <= y <= y2


def _to_contract(label: str, confidence: float, box: Box, w: int, h: int) -> DetectedObject:
    """Pixel box -> normalized contract box, clamped to [0, 1]."""
    x1, y1, x2, y2 = box

    def nx(v: float) -> float:
        return min(1.0, max(0.0, v / w))

    def ny(v: float) -> float:
        return min(1.0, max(0.0, v / h))

    return DetectedObject(
        label=label,
        confidence=min(1.0, max(0.0, confidence)),
        bbox=BBox(x1=nx(x1), y1=ny(y1), x2=nx(x2), y2=ny(y2)),
    )
