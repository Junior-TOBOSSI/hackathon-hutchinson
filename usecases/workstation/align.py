"""Align a photo of the station onto the reference image (SIFT + RANSAC homography).

Why: the reference image is provided by the client, our photo comes from our camera. Even
with a fixed camera, the two never match pixel for pixel (small shift, rotation, zoom).
Without alignment, the pixel difference would light up everywhere.

How:
1. SIFT finds distinctive points (corners, patterns) in both images.
2. Each point of the photo is matched to its most similar point in the reference; Lowe's
   ratio test keeps only unambiguous matches.
3. RANSAC estimates the homography (the 3x3 transform of a plane seen from two
   viewpoints) while rejecting the wrong matches ("outliers").
4. The photo is warped into the reference frame. ``valid`` marks the pixels that really
   come from the photo (the borders of the warped photo are empty).

If too few matches agree, the alignment is declared FAILED: the analyzer then answers
"a_verifier" instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_sift = None


def _detector() -> cv2.SIFT:
    global _sift
    if _sift is None:
        _sift = cv2.SIFT_create(nfeatures=4000)
    return _sift


@dataclass
class Alignment:
    ok: bool
    aligned: np.ndarray | None  # photo warped into the reference frame
    valid: np.ndarray | None  # bool (H, W) of the reference: pixels covered by the photo
    inliers: int
    reason: str = ""
    homography: np.ndarray | None = None  # 3x3, photo pixels -> reference pixels


def align_to_reference(
    image: np.ndarray,
    reference: np.ndarray,
    min_inliers: int = 25,
    ratio: float = 0.75,
    max_side: int = 1000,
) -> Alignment:
    """Warp ``image`` onto ``reference``. Keypoints are searched on images reduced to
    ``max_side`` pixels (faster, and enough for a homography)."""
    sift = _detector()
    s_img = min(1.0, max_side / max(image.shape[:2]))
    s_ref = min(1.0, max_side / max(reference.shape[:2]))
    kp1, des1 = sift.detectAndCompute(_small_gray(image, s_img), None)
    kp2, des2 = sift.detectAndCompute(_small_gray(reference, s_ref), None)
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return Alignment(False, None, None, 0, "not enough keypoints")

    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des1, des2, k=2)
    good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < ratio * n.distance]
    if len(good) < max(4, min_inliers):
        return Alignment(False, None, None, len(good), f"only {len(good)} good matches")

    src = np.float32([kp1[m.queryIdx].pt for m in good]) / s_img
    dst = np.float32([kp2[m.trainIdx].pt for m in good]) / s_ref
    homography, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    if homography is None or inliers < min_inliers:
        return Alignment(False, None, None, inliers, f"only {inliers} consistent matches")

    h, w = reference.shape[:2]
    aligned = cv2.warpPerspective(image, homography, (w, h), flags=cv2.INTER_LINEAR)
    coverage = cv2.warpPerspective(
        np.full(image.shape[:2], 255, np.uint8), homography, (w, h), flags=cv2.INTER_NEAREST
    )
    # Erode a little: the very border of the warped photo is interpolated with black.
    valid = cv2.erode(coverage, np.ones((7, 7), np.uint8)) > 0
    if valid.mean() < 0.5:
        return Alignment(
            False, None, None, inliers, "the photo covers less than half the reference"
        )
    return Alignment(True, aligned, valid, inliers, homography=homography)


def _small_gray(image: np.ndarray, scale: float) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return gray
