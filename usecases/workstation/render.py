"""Draw the result of the workstation analyzer ON THE ORIGINAL PHOTO.

The analyzer works in the frame of the reference view (the photo is aligned on it). To
show the boxes on the photo as it was taken, every point is sent back through the
inverse of the alignment homography (align.py).

Drawn:
- zones (``empty_zones``): green outline if empty, RED if something is in it;
- element slots (``element_slots``): green RECTANGLE if the element is in its place, RED
  if not;
- found objects: ORANGE rectangle for an unknown object, MAGENTA for a person, with its
  label;
- a banner with the verdict only (OK / CHECK / NOK), no score.
"""

from __future__ import annotations

import cv2
import numpy as np

from usecases.workstation.model import ZoneWorkstationAnalyzer
from visionhub.contracts import AnalysisResult, Decision

GREEN, RED, ORANGE, MAGENTA = (60, 170, 60), (40, 40, 220), (0, 150, 255), (200, 60, 200)
VERDICT = {
    Decision.CONFORME: ("OK", (60, 160, 60)),
    Decision.A_VERIFIER: ("CHECK", (0, 150, 240)),
    Decision.ANOMALIE: ("NOK", (40, 40, 210)),
}


def render(
    image: np.ndarray,
    analyzer: ZoneWorkstationAnalyzer,
    result: AnalysisResult,
    decision: Decision,
    scale: float = 2.0,
) -> np.ndarray:
    """Annotated copy of ``image`` (BGR), enlarged by ``scale`` so that labels are readable."""
    out = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    view, alignment = getattr(analyzer, "last_view_obj", None), analyzer.last_alignment
    if view is not None and alignment is not None and alignment.homography is not None:
        h, w = view.image.shape[:2]
        back = np.linalg.inv(alignment.homography)

        def to_photo(points: np.ndarray) -> np.ndarray:
            """Normalized points of the reference -> pixels of the enlarged photo."""
            pixels = np.asarray(points, np.float64).reshape(-1, 1, 2) * [w - 1, h - 1]
            return (cv2.perspectiveTransform(pixels, back).reshape(-1, 2) * scale).astype(np.int32)

        busy = {f.split("@", 1)[1] for f in result.details.misplaced if "@" in f}
        for name, polygon in view.zones.items():
            colour = RED if name in busy else GREEN
            _outline(out, to_photo(polygon), colour, 3 if name in busy else 2, name)
        for name, polygon in view.slots.items():
            missing = name in result.details.missing or name in result.details.misplaced
            label = f"{name}: missing / moved" if missing else name
            _outline(out, to_photo(polygon), RED if missing else GREEN, 2, label, rect=True)
        # Only what matters is drawn: unknown objects, persons, and detections that are
        # part of a problem. Other detections (e.g. the press seen as a "tv") decide
        # nothing and would only confuse the operator.
        named = {f.split("@", 1)[0] for f in result.details.misplaced if "@" in f}
        for obj in result.details.detected:
            if obj.label not in named | {"unknown_object", "person"}:
                continue
            b = obj.bbox
            quad = to_photo([(b.x1, b.y1), (b.x2, b.y1), (b.x2, b.y2), (b.x1, b.y2)])
            colour = MAGENTA if obj.label == "person" else ORANGE
            name = "unknown object" if obj.label == "unknown_object" else obj.label
            _outline(out, quad, colour, 3, f"{name} {obj.confidence:.2f}", rect=True)
    return _banner(out, result, decision)


def _outline(
    img: np.ndarray, points: np.ndarray, colour, thickness: int, label: str, rect: bool = False
) -> None:
    """Outline + label. ``rect``: an upright rectangle around the points (bounding box),
    instead of the exact shape tilted by the camera perspective."""
    if rect:
        h, w = img.shape[:2]
        x1, y1 = np.clip(points.min(axis=0), 0, [w - 1, h - 1])
        x2, y2 = np.clip(points.max(axis=0), 0, [w - 1, h - 1])
        points = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.int32)
    cv2.polylines(img, [points], True, colour, thickness, cv2.LINE_AA)
    x, y = int(points[:, 0].min()), int(points[:, 1].min())
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    y = max(th + 4, y)
    cv2.rectangle(img, (x, y - th - 4), (x + tw + 4, y), colour, -1)
    cv2.putText(
        img, label, (x + 2, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
    )


def _banner(img: np.ndarray, result: AnalysisResult, decision: Decision) -> np.ndarray:
    """Verdict only (OK / CHECK / NOK): the operator does not need the score."""
    text, colour = VERDICT[decision]
    bar = np.full((48, img.shape[1], 3), colour, np.uint8)
    cv2.putText(
        bar,
        text,
        (12, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return np.vstack([bar, img])


def describe(result: AnalysisResult) -> list[str]:
    """The problems found, in plain English, for the operator screen."""
    lines = []
    for name in result.details.missing:
        lines.append(f"{name}: not in its place")
    for item in result.details.misplaced:
        if item == "alignment_failed":
            lines.append("Photo cannot be aligned with the reference: to check")
        elif "@" in item:
            what, zone = item.split("@", 1)
            who = {"person": "Person", "unknown_object": "Object"}.get(what, what)
            lines.append(f"{who} in {zone}")
        else:
            lines.append(f"{item}: moved")
    return lines
