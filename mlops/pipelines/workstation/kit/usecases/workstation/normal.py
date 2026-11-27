"""Learn what "normal" looks like from several conforming photos of a station.

Why: a single reference image is not enough. Conforming photos already differ from each
other (a bottle moved by a few centimetres, a bin slightly turned, hatching rendered a bit
differently, a sign present or not). Compared pixel by pixel with ONE image, every
conforming photo would raise an alert.

How: every conforming photo is aligned on the view's reference (align.py), then for each
pixel we keep
- the MEAN colour over the conforming photos (the "typical" station), and
- the SPREAD (standard deviation) of that colour: low on a fixed part (bench edge, floor),
  high where things normally vary (a bottle, a cable, the hatching).

At analysis time, a pixel counts as changed only if it differs from the mean by more than
``k`` times its normal spread (and by at least ``diff_threshold`` grey levels). A change
where things never vary is caught; normal variation is ignored.

This is the statistical idea behind classic anomaly detection ("z-score"), without any
neural network: it is fast, explainable, and learns from a dozen photos per view.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from usecases.workstation.align import align_to_reference

log = logging.getLogger(__name__)


@dataclass
class NormalModel:
    mean: np.ndarray  # float32 (H, W, 3), smoothed BGR mean of the conforming photos
    spread: np.ndarray  # float32 (H, W), largest per-channel standard deviation
    count: int  # number of photos used


def smooth(image: np.ndarray) -> np.ndarray:
    """Same light blur as the change detection (removes the camera noise)."""
    return cv2.GaussianBlur(image, (5, 5), 0).astype(np.float32)


def learn_normal(
    reference: np.ndarray, photos: list[np.ndarray], min_inliers: int = 25
) -> NormalModel | None:
    """Normal model of a view from conforming photos (those that do not align are skipped)."""
    aligned, valid = [], []
    for photo in photos:
        alignment = align_to_reference(photo, reference, min_inliers=min_inliers)
        if alignment.ok:
            aligned.append(alignment.aligned)
            valid.append(alignment.valid)
    return normal_from_aligned(reference, aligned, valid)


def normal_from_aligned(
    reference: np.ndarray, aligned: list[np.ndarray], valid: list[np.ndarray]
) -> NormalModel | None:
    """Mean and spread of photos ALREADY aligned on the reference.

    Returns None with fewer than 2 photos (no spread can be estimated)."""
    if len(aligned) < 2:
        log.warning("Only %d conforming photos aligned: no normal model", len(aligned))
        return None
    stack = np.stack([smooth(a) for a in aligned])
    covered = np.stack(valid)
    # Pixels outside a photo (warp borders) are filled with the reference before stats.
    ref = np.broadcast_to(smooth(reference), stack.shape)
    stack = np.where(covered[..., None], stack, ref)
    return NormalModel(stack.mean(axis=0), stack.std(axis=0).max(axis=2), len(aligned))
