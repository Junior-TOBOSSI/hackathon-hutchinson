"""Workstation analyzer (5S): compare ONE photo of the station with its reference.

Business need: at the start of the shift, one photo of the station is compared with the
reference, to find (a) what is NOT IN ITS PLACE and (b) any object OR PERSON in a zone
that must stay empty. The station (views, boxes, conforming photos) is described in
``stations/<name>.yaml`` (station.py); config.yaml points to it.

For every photo:

0. ALIGN: the photo is warped onto each reference VIEW (one per camera framing, align.py)
   and the view with the most consistent matches is used. If none aligns, the answer is
   "alignment_failed" with a medium score (a_verifier): a human looks, nothing is guessed.
1. CHANGES: one mask of the pixels that differ from what is NORMAL for that view. Normal
   is learned from several conforming photos (normal.py: per-pixel mean and spread), so
   the normal variation between conforming photos is not an alert. Without conforming
   photos, the single reference image is used.
2. ELEMENT SLOTS (``element_slots``): if a large share of an element's slot changed, the
   element is not in its place: ``details.missing`` (``misplaced`` if seen elsewhere).
3. ZONES (``empty_zones``): any change in a zone is a violation, written
   ``"<label>@<zone>"`` in ``details.misplaced``; ``unknown_object`` when no detection
   names it. The optional detector only NAMES changes, it never raises an alert alone.
4. SCORE (in [0, 1], higher = worse): the score of the worst problem; the common
   decision layer turns it into conforme / a_verifier / anomalie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from usecases.workstation.align import align_to_reference
from usecases.workstation.detector import REPO_ROOT, Detection, build_detector
from usecases.workstation.normal import NormalModel, normal_from_aligned
from usecases.workstation.station import analyzer_params, load_station
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


@dataclass
class View:
    """One reference image of the station and the regions drawn on it.

    A station can have SEVERAL views (e.g. one per camera framing): the photo is compared
    with the view it aligns best with. Zone and slot names are shared across views, so
    the output does not depend on which view was used.
    """

    name: str
    image: np.ndarray | None
    zones: dict[str, Polygon] = field(default_factory=dict)
    slots: dict[str, Polygon] = field(default_factory=dict)
    normal: NormalModel | None = None  # learned from conforming photos (normal.py)


class ZoneWorkstationAnalyzer(Analyzer):
    use_case = UseCase.WORKSTATION
    name = "zone-workstation"
    version = "0.3.0"

    # ------------------------------------------------------------------ loading

    def load(self, config: dict[str, Any]) -> None:
        # A station file (stations/<name>.yaml) describes the views and the normal photos.
        if config.get("station"):
            root = Path(config.get("data_root") or "data").expanduser()
            station = load_station(
                config["station"], root if root.is_absolute() else REPO_ROOT / root
            )
            config = {**analyzer_params(station), **config}
        self.detector = build_detector(config)
        self.expected: list[str] = list(config.get("expected_objects") or [])
        # Labels never judged in zones. Empty by default: a person IS a violation.
        self.ignore_labels: set[str] = set(config.get("ignore_labels") or [])
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
        self.normal_k = float(config.get("normal_k", 4.0))
        self.min_box_fill = float(config.get("min_box_fill", 0.05))

        # One view (top-level keys) or several (``views:`` list, one per camera framing).
        raw_views = config.get("views") or [
            {
                "name": "main",
                "reference_image": config.get("reference_image"),
                "empty_zones": config.get("empty_zones"),
                "element_slots": config.get("element_slots"),
            }
        ]
        self.views = [
            View(
                name=str(v.get("name", f"view{i}")),
                image=self._load_reference(v.get("reference_image")),
                zones=_polygons(v.get("empty_zones")),
                slots=_polygons(v.get("element_slots")),
            )
            for i, v in enumerate(raw_views)
        ]
        self._masks: dict[tuple[str, int, int], dict[str, np.ndarray]] = {}
        self.learn_normal(list(config.get("normal_images") or []))
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

    def learn_normal(self, paths: list[str]) -> None:
        """Learn each view's normal variability from conforming photos (normal.py).

        Each photo goes to the view it aligns best with; photos aligning nowhere are
        skipped. Without photos, a view compares with its single reference image."""
        # Each reference image is itself a conforming photo of its view.
        groups: dict[str, tuple[list, list]] = {
            v.name: ([v.image], [np.ones(v.image.shape[:2], bool)])
            if v.image is not None
            else ([], [])
            for v in self.views
        }
        for path in paths:
            image = cv2.imread(str(Path(path).expanduser()))
            picked = self._pick_view(image) if image is not None else None
            if picked is not None:
                view, alignment = picked
                groups[view.name][0].append(alignment.aligned)
                groups[view.name][1].append(alignment.valid)
        for view in self.views:
            aligned, valid = groups[view.name]
            if view.image is not None and len(aligned) >= 2:
                view.normal = normal_from_aligned(view.image, aligned, valid)
                log.info("View %s: normal model from %d photos", view.name, len(aligned))

    @property
    def reference(self) -> np.ndarray | None:
        """Reference image of the first view."""
        return self.views[0].image

    def reset_reference(self, image: np.ndarray) -> None:
        """Take a new reference for the first view (e.g. station rearranged on purpose)."""
        self.views[0].image = image.copy()
        self._streak.clear()

    def _pick_view(self, image: np.ndarray):
        """Align the photo on every view; keep the one with the most consistent matches."""
        best = None
        for view in self.views:
            if view.image is None:
                continue
            alignment = align_to_reference(image, view.image, min_inliers=self.min_inliers)
            if alignment.ok and (best is None or alignment.inliers > best[1].inliers):
                best = (view, alignment)
        return best

    # ------------------------------------------------------------------ analysis

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        if self.reference is None:
            self.reset_reference(image)

        view, valid = self.views[0], None
        self.last_alignment = None
        if self.align:
            picked = self._pick_view(image)
            if picked is None:
                log.warning("Frame %s: alignment failed on every view", meta.frame_id)
                self.last_view, self.last_view_obj = "-", None
                return self._result(self.alignment_failed_score, [], [], [ALIGNMENT_FAILED])
            view, alignment = picked
            image, valid = alignment.aligned, alignment.valid
            self.last_alignment = alignment
        self.last_view = view.name
        self.last_view_obj = view

        h, w = image.shape[:2]
        detections = self.detector(image)
        detected = [_to_contract(d.label, d.confidence, d.box, w, h) for d in detections]
        labels = {d.label for d in detections}

        candidates: Problems = {}
        for label in self.expected:
            if label not in labels:
                candidates[f"missing:{label}"] = (self.missing_score, None)

        if view.normal is not None:
            base, spread = view.normal.mean, view.normal.spread
        else:
            base, spread = view.image, None
        changed = change_mask(image, base, self.diff_threshold, valid, spread, self.normal_k)
        masks = self._region_masks(view, (h, w))
        ignored = [d for d in detections if d.label in self.ignore_labels]
        if ignored:
            changed &= ~boxes_mask([d.box for d in ignored], (h, w))
        objects = [d for d in detections if d.label not in self.ignore_labels]
        usable = valid if valid is not None else np.ones((h, w), dtype=bool)

        for slot in view.slots:
            candidates.update(
                self._slot_problems(slot, masks[f"slot:{slot}"], changed, usable, objects)
            )
        for zone in view.zones:
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
                expected=sorted(set(self.expected).union(*(v.slots for v in self.views))),
                detected=detected,
                missing=missing,
                misplaced=misplaced,
            ),
        )

    def _region_masks(self, view: View, shape: tuple[int, int]) -> dict[str, np.ndarray]:
        """Masks of the zones and slots of a view for this image size, cached."""
        key = (view.name, *shape)
        if key not in self._masks:
            masks = {f"zone:{n}": polygon_mask(p, shape) for n, p in view.zones.items()}
            masks |= {f"slot:{n}": polygon_mask(p, shape) for n, p in view.slots.items()}
            self._masks[key] = masks
        return self._masks[key]

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

        # 1. Detected objects or persons whose box overlaps the zone AND covers a change:
        #    the detector only NAMES what changed, it never raises an alert on its own
        #    (an object that is normally there, or the whole bench seen as a
        #    "refrigerator" around a small change, must not count).
        #    Score = the stronger of the two evidences (detector confidence, size of the
        #    change): a hesitant detector never LOWERS a change.
        inside = []
        for d in objects:
            if box_overlap(d.box, mask) < self.min_overlap:
                continue
            if _box_fill(d.box, changed & mask) < self.min_box_fill:
                continue  # the change is a speck in a huge box: the box is the scene, not it
            explained = [change_score(b.area) for b in blobs if _contains(d.box, b.center)]
            if not explained:
                continue
            inside.append(d)
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


def _box_fill(box: Box, changed: np.ndarray) -> float:
    """Share of the box covered by changed pixels."""
    x1, y1, x2, y2 = (max(0, v) for v in box)
    area = max(1, (x2 - x1) * (y2 - y1))
    return float(changed[y1:y2, x1:x2].sum()) / area


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
