"""Common preprocessing, applied once before every analyzer receives the image."""

from __future__ import annotations

import logging

import numpy as np

from visionhub.config import Settings

log = logging.getLogger(__name__)
_warned = False


def crop_roi(image: np.ndarray, roi: tuple[int, int, int, int] | None) -> np.ndarray:
    """Crop to the region of interest (x, y, w, h) in pixels, clamped to the image.

    Returns the full image when ``roi`` is None or does not overlap the image.
    """
    if roi is None:
        return image
    x, y, w, h = roi
    height, width = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    if x1 <= x0 or y1 <= y0:
        log.warning("ROI %s is outside the image (%dx%d), ignored", roi, width, height)
        return image
    return image[y0:y1, x0:x1]


def anonymize(image: np.ndarray) -> np.ndarray:
    """Hook for face blurring. STUB: currently returns the image unchanged.

    Intended implementation (to be validated by the team): detect faces with a light
    CPU detector (e.g. OpenCV DNN / YuNet), then apply a strong Gaussian blur on each
    face box, IN PLACE, before any analyzer sees the image. Nothing is stored either way:
    the platform only keeps events, never images.
    """
    global _warned
    if not _warned:
        log.warning("ANONYMIZE is enabled but anonymize() is still a stub: no blurring applied")
        _warned = True
    return image


def preprocess(image: np.ndarray, settings: Settings) -> np.ndarray:
    image = crop_roi(image, settings.roi_box())
    if settings.anonymize:
        image = anonymize(image)
    return image
