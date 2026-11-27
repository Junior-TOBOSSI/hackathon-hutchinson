"""Zone geometry and reference-image difference. Pure NumPy / OpenCV, no model.

Two questions are answered here, for one zone that must stay empty:

1. "How much of this detected object lies in the zone?"  -> ``box_overlap``
2. "Did anything appear in the zone, even an object no model knows?" -> ``changed_blobs``

Both use the same binary mask of the zone (``polygon_mask``), computed once per image size.
Polygons are NORMALIZED ([x, y] in [0, 1]), like the boxes of the contract, so a zone stays
valid if the camera resolution changes.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

Polygon = list[tuple[float, float]]
Box = tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels


def validate_polygon(name: str, points: object) -> Polygon:
    """Check a zone read from config.yaml: at least 3 points, coordinates in [0, 1]."""
    try:
        polygon = [(float(x), float(y)) for x, y in points]  # type: ignore[union-attr]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"zone {name!r}: expected a list of [x, y] points") from exc
    if len(polygon) < 3:
        raise ValueError(f"zone {name!r}: a polygon needs at least 3 points")
    if not all(0.0 <= v <= 1.0 for point in polygon for v in point):
        raise ValueError(f"zone {name!r}: coordinates must be normalized in [0, 1]")
    return polygon


def polygon_mask(polygon: Polygon, shape: tuple[int, int]) -> np.ndarray:
    """Boolean mask (H, W), True inside the normalized polygon."""
    h, w = shape
    points = np.round(np.array(polygon) * [w - 1, h - 1]).astype(np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [points], 1)
    return mask.astype(bool)


def box_overlap(box: Box, mask: np.ndarray) -> float:
    """Share of the box area that lies inside the mask, in [0, 1].

    Better than the usual "is the box centre in the zone?" test: an object lying across
    the border of the zone is still caught.
    """
    x1, y1, x2, y2 = box
    h, w = mask.shape
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return float(mask[y1:y2, x1:x2].mean())


def boxes_mask(boxes: list[Box], shape: tuple[int, int]) -> np.ndarray:
    """Boolean mask (H, W), True inside any of the boxes (used to ignore the operator)."""
    mask = np.zeros(shape, dtype=bool)
    for x1, y1, x2, y2 in boxes:
        mask[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)] = True
    return mask


@dataclass(frozen=True)
class Blob:
    """A connected region that differs from the reference image."""

    box: Box
    area: int  # pixels

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2


def _smooth(image: np.ndarray) -> np.ndarray:
    """Float BGR image, lightly blurred: the blur removes the camera noise."""
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return cv2.GaussianBlur(image, (5, 5), 0).astype(np.float32)


def change_mask(
    image: np.ndarray,
    reference: np.ndarray,
    diff_threshold: float,
    valid: np.ndarray | None = None,
    spread: np.ndarray | None = None,
    k: float = 4.0,
) -> np.ndarray:
    """Boolean mask (H, W) of the pixels that differ from the reference image.

    Computed ONCE per image, then read by every zone and every element slot.
    Steps: blur, global brightness compensation, absolute difference PER COLOUR CHANNEL
    (the largest one is kept), threshold, morphological cleaning.
    ``valid`` (optional) marks the pixels that exist in both images (after alignment, the
    borders of the warped photo are empty and must not count as changes).

    Why colour and not grayscale: an orange box on a grey bench can have the SAME
    brightness as the bench; in grayscale it would be invisible.

    With a learned normal model (normal.py), ``reference`` is the MEAN of the conforming
    photos (float32, already smoothed) and ``spread`` their per-pixel standard deviation:
    the threshold becomes max(diff_threshold, k * spread), so normal variation is ignored.
    """
    h, w = image.shape[:2]
    if reference.shape[:2] != (h, w):
        reference = cv2.resize(reference, (w, h), interpolation=cv2.INTER_AREA)
    if valid is None:
        valid = np.ones((h, w), dtype=bool)

    current = _smooth(image)
    ref = reference if reference.dtype == np.float32 else _smooth(reference)
    # If the whole scene got brighter or darker (light switched on, cloud), scale each
    # channel back to the reference level, so that only LOCAL changes remain.
    current *= ref[valid].mean(axis=0) / np.maximum(current[valid].mean(axis=0), 1.0)

    threshold: float | np.ndarray = diff_threshold
    if spread is not None:
        if spread.shape != (h, w):
            spread = cv2.resize(spread, (w, h), interpolation=cv2.INTER_LINEAR)
        threshold = np.maximum(diff_threshold, k * spread)
    changed = (np.abs(current - ref).max(axis=2) > threshold) & valid

    # Opening removes isolated pixels, closing fills small holes inside an object.
    kernel = np.ones((5, 5), np.uint8)
    cleaned = cv2.morphologyEx(changed.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    return cleaned.astype(bool)


def blobs_in(changed: np.ndarray, min_area: int, group_px: int = 0) -> list[Blob]:
    """Connected regions of a boolean change mask larger than ``min_area`` pixels.

    ``group_px`` > 0 merges pieces closer than that many pixels into one region: the
    edges of an object (a bin, a crate) often split its change in two, and the box must
    cover the whole object. The area counts only the changed pixels."""
    mask = changed.astype(np.uint8)
    groups = mask
    if group_px > 0:
        size = 2 * group_px + 1
        groups = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    n, labels = cv2.connectedComponents(groups, connectivity=8)
    blobs = []
    for i in range(1, n):  # label 0 is the background
        ys, xs = np.nonzero((labels == i) & changed)
        if len(xs) >= min_area:
            box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            blobs.append(Blob(box=box, area=len(xs)))
    return blobs


def changed_blobs(
    image: np.ndarray,
    reference: np.ndarray,
    zone_mask: np.ndarray,
    diff_threshold: float,
    min_area: int,
    ignore_mask: np.ndarray | None = None,
) -> list[Blob]:
    """Regions of the zone that differ from the reference (change_mask + blobs_in)."""
    changed = change_mask(image, reference, diff_threshold) & zone_mask
    if ignore_mask is not None:
        changed &= ~ignore_mask
    return blobs_in(changed, min_area)
