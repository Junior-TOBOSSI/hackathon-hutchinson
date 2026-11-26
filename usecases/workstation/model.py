"""Workstation analyzer: compare ONE photo of the station with the reference image.

Business need (client, 2026-11-26): at the start of the shift, one photo of the station is
taken and compared with the reference image provided by the client, to find
(a) what is NOT IN ITS PLACE and (b) any object OR PERSON in a zone that must stay empty.

For every photo:

0. ALIGN (``align: true``): the photo is warped onto the reference (align.py). If the
   alignment fails, the answer is "alignment_failed" with a medium score (a_verifier):
   a human looks, the system does not guess.
1. IDENTIFY: an object detector runs on the whole (aligned) image; every detection goes to
   ``details.detected``. Expected labels that are not seen go to ``details.missing``.
2. CHANGES: one mask of the pixels that differ from the reference (zones.change_mask).
3. ELEMENT SLOTS (``element_slots``): each element has its place drawn on the reference.
   If a large share of the slot changed, the element is not in its place: it goes to
   ``missing`` (or ``misplaced`` if the detector sees it elsewhere).
4. EMPTY ZONES (``empty_zones``): a detected object or person overlapping the zone, or a
   changed region no detection explains (``unknown_object``), is a violation, written
   ``"<label>@<zone>"`` in ``details.misplaced``.
5. PERSISTENCE (``persistence_frames``): 1 for a single photo; >1 only for a video stream.
6. SCORE (in [0, 1], higher = worse): the score of the worst problem.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from usecases.workstation.align import align_to_reference
from usecases.workstation.detector import REPO_ROOT, Detection, build_detector
from usecases.workstation.zones import (
    Box,
    Polygon,
    blobs_in,
    box_overlap,
    boxes_mask,
    change_mask,
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
ALIGNMENT_FAILED = "alignment_failed"

Problems = dict[str, tuple[float, DetectedObject | None]]


class ZoneWorkstationAnalyzer(Analyzer):
    use_case = UseCase.WORKSTATION
    name = "zone-workstation"
    version = "0.2.0"

    # ------------------------------------------------------------------ loading

    def load(self, config: dict[str, Any]) -> None:
        self.detector = build_detector(config)
        self.expected: list[str] = list(config.get("expected_objects") or [])
        # Labels never judged in zones. Empty by default: a person IS a violation.
        self.ignore_labels: set[str] = set(config.get("ignore_labels") or [])
        self.zones: dict[str, Polygon] = _polygons(config.get("empty_zones"))
        self.slots: dict[str, Polygon] = _polygons(config.get("element_slots"))
        self.min_overlap = float(config.get("min_overlap", 0.15))
        self.diff_threshold = float(config.get("diff_threshold", 35))
        self.min_blob_area = float(config.get("min_blob_area", 0.01))
        self.full_blob_area = float(config.get("full_blob_area", 0.05))
        self.unknown_min_score = float(config.get("unknown_min_score", 0.45))
        self.slot_min_change = float(config.get("slot_min_change", 0.25))
        self.slot_full_change = float(config.get("slot_full_change", 0.6))
        self.persistence_frames = max(1, int(config.get("persistence_frames", 1)))
        self.missing_score = float(config.get("missing_score", 0.5))
        self.align = bool(config.get("align", False))
        self.min_inliers = int(config.get("min_inliers", 25))
        self.alignment_failed_score = float(config.get("alignment_failed_score", 0.5))

        self.reference = self._load_reference(config.get("reference_image"))
        self._masks: dict[tuple[int, int], dict[str, np.ndarray]] = {}
        self._streak: dict[str, int] = {}  # problem key -> consecutive frames seen

    def _load_reference(self, path: str | None) -> np.ndarray | None:
        """Reference image of the station. None -> the first analyzed frame is used."""
        if not path:
            log.info("No reference_image: the first analyzed frame becomes the reference")
            return None
        full = Path(path).expanduser()
        full = full if full.is_absolute() else REPO_ROOT / full
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
        if self.reference is None:
            self.reset_reference(image)

        valid = None
        if self.align:
            alignment = align_to_reference(image, self.reference, min_inliers=self.min_inliers)
            if not alignment.ok:
                log.warning("Frame %s: alignment failed (%s)", meta.frame_id, alignment.reason)
                return self._result(self.alignment_failed_score, [], [], [ALIGNMENT_FAILED])
            image, valid = alignment.aligned, alignment.valid

        h, w = image.shape[:2]
        detections = self.detector(image)
        detected = [_to_contract(d.label, d.confidence, d.box, w, h) for d in detections]
        labels = {d.label for d in detections}

        candidates: Problems = {}
        for label in self.expected:
            if label not in labels:
                candidates[f"missing:{label}"] = (self.missing_score, None)

        changed = change_mask(image, self.reference, self.diff_threshold, valid)
        masks = self._region_masks((h, w))
        ignored = [d for d in detections if d.label in self.ignore_labels]
        if ignored:
            changed &= ~boxes_mask([d.box for d in ignored], (h, w))
        objects = [d for d in detections if d.label not in self.ignore_labels]
        usable = valid if valid is not None else np.ones((h, w), dtype=bool)

        for slot in self.slots:
            candidates.update(
                self._slot_problems(slot, masks[f"slot:{slot}"], changed, usable, objects)
            )
        for zone in self.zones:
            candidates.update(
                self._zone_problems(zone, masks[f"zone:{zone}"], changed, objects, w, h)
            )

        confirmed = self._confirm(candidates)
        missing = [k.split(":", 1)[1] for k in confirmed if k.startswith("missing:")]
        misplaced = [k.split(":", 1)[1] for k in confirmed if k.startswith("moved:")]
        misplaced += [k for k in confirmed if "@" in k]
        detected += [obj for _, obj in confirmed.values() if obj is not None]
        score = max((s for s, _ in confirmed.values()), default=0.0)
        return self._result(score, detected, list(dict.fromkeys(missing)), misplaced)

    def _result(
        self, score: float, detected: list, missing: list[str], misplaced: list[str]
    ) -> AnalysisResult:
        return AnalysisResult(
            use_case=self.use_case,
            score=min(1.0, max(0.0, score)),
            model_name=f"{self.name}+{self.detector.name}",
            model_version=self.version,
            details=WorkstationDetails(
                expected=sorted(set(self.expected) | set(self.slots)),
                detected=detected,
                missing=missing,
                misplaced=misplaced,
            ),
        )

    def _region_masks(self, shape: tuple[int, int]) -> dict[str, np.ndarray]:
        """Masks of zones and slots for this image size, computed once and cached."""
        if shape not in self._masks:
            masks = {f"zone:{n}": polygon_mask(p, shape) for n, p in self.zones.items()}
            masks |= {f"slot:{n}": polygon_mask(p, shape) for n, p in self.slots.items()}
            self._masks[shape] = masks
        return self._masks[shape]

    def _slot_problems(
        self,
        slot: str,
        mask: np.ndarray,
        changed: np.ndarray,
        usable: np.ndarray,
        objects: list[Detection],
    ) -> Problems:
        """An element is not in its place when a large share of its slot changed."""
        area = int((mask & usable).sum())
        if area == 0:  # slot outside the part of the photo we can compare
            return {}
        share = float((changed & mask).sum()) / area
        if share < self.slot_min_change:
            return {}
        score = min(1.0, share / self.slot_full_change)
        # Seen elsewhere by the detector (label == slot name): moved, not missing.
        if any(d.label == slot and box_overlap(d.box, mask) < self.min_overlap for d in objects):
            return {f"moved:{slot}": (score, None)}
        return {f"missing:{slot}": (score, None)}

    def _zone_problems(
        self,
        zone: str,
        mask: np.ndarray,
        changed: np.ndarray,
        objects: list[Detection],
        w: int,
        h: int,
    ) -> Problems:
        problems: Problems = {}
        zone_area = max(int(mask.sum()), 1)
        blobs = blobs_in(changed & mask, max(1, int(self.min_blob_area * zone_area)))

        def change_score(area: int) -> float:
            # Client rule "no element in the zone": any change above the noise floor is
            # worth at least a check (unknown_min_score), up to 1 at full_blob_area.
            growth = min(1.0, area / (self.full_blob_area * zone_area))
            return self.unknown_min_score + (1.0 - self.unknown_min_score) * growth

        # 1. Detected objects or persons whose box overlaps the zone: they get a NAME.
        #    Score = the stronger of the two evidences (detector confidence, size of the
        #    change), so that a hesitant detector never LOWERS a clear change.
        inside = [d for d in objects if box_overlap(d.box, mask) >= self.min_overlap]
        for d in inside:
            explained = [change_score(b.area) for b in blobs if _contains(d.box, b.center)]
            score = max([d.confidence, *explained])
            key = f"{d.label}@{zone}"
            problems[key] = (max(score, problems.get(key, (0.0, None))[0]), None)

        # 2. Changes no in-zone detection explains: an unknown object.
        unknown = [b for b in blobs if not any(_contains(d.box, b.center) for d in inside)]
        if unknown:
            biggest = max(unknown, key=lambda b: b.area)
            confidence = change_score(biggest.area)
            obj = _to_contract(UNKNOWN, confidence, biggest.box, w, h)
            problems[f"{UNKNOWN}@{zone}"] = (confidence, obj)
        return problems

    def _confirm(self, candidates: Problems) -> Problems:
        """Keep only the problems seen on ``persistence_frames`` consecutive frames."""
        self._streak = {key: self._streak.get(key, 0) + 1 for key in candidates}
        return {k: v for k, v in candidates.items() if self._streak[k] >= self.persistence_frames}


def _polygons(raw: object) -> dict[str, Polygon]:
    return {name: validate_polygon(name, pts) for name, pts in (raw or {}).items()}  # type: ignore[union-attr]


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
