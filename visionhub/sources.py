"""Image sources, selected with the SOURCE setting.

Each source is a generator yielding BGR uint8 images (H, W, 3). The pipeline adds the
metadata and controls the frame rate.

- synthetic : images drawn with OpenCV (default, needs no camera and no data)
- folder    : images of a folder (SOURCE_PATH), looped forever
- video     : a video file (SOURCE_PATH), looped forever
- webcam    : a camera (WEBCAM_INDEX)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from visionhub.config import Settings

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def synthetic_frame(index: int, seed: int = 0, size: tuple[int, int] = (480, 640)) -> np.ndarray:
    """Draw a fake workstation scene: a part, some tools, and a person silhouette."""
    rng = np.random.default_rng(seed + index)
    h, w = size
    img = np.full((h, w, 3), 70, dtype=np.uint8)
    cv2.rectangle(img, (0, int(h * 0.55)), (w, h), (110, 110, 110), -1)  # workbench

    # The part (quality): a disk, sometimes with a dark scratch.
    center = (int(w * 0.3), int(h * 0.35))
    cv2.circle(img, center, 60, (180, 180, 185), -1)
    cv2.circle(img, center, 20, (90, 90, 95), -1)
    if rng.random() < 0.15:
        x, y = center[0] + int(rng.integers(-40, 20)), center[1] + int(rng.integers(-40, 20))
        cv2.line(img, (x, y), (x + 30, y + 15), (30, 30, 30), 3)

    # Tools on the bench (workstation), one sometimes missing.
    colors = [(40, 140, 220), (60, 200, 60), (200, 120, 40), (180, 60, 180)]
    for i, color in enumerate(colors):
        if rng.random() < 0.1:
            continue
        x = int(w * (0.08 + 0.22 * i)) + int(rng.integers(-5, 6))
        cv2.rectangle(img, (x, int(h * 0.7)), (x + 80, int(h * 0.85)), color, -1)

    # A person silhouette (safety), no face details at all.
    px = int(w * 0.75) + int(rng.integers(-20, 21))
    cv2.circle(img, (px, int(h * 0.2)), 25, (150, 170, 200), -1)
    cv2.rectangle(img, (px - 35, int(h * 0.27)), (px + 35, int(h * 0.55)), (0, 200, 255), -1)

    noise = rng.normal(0, 6, img.shape)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    cv2.putText(img, f"SYNTHETIC #{index}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,) * 3, 1)
    return img


def synthetic_source(seed: int = 0) -> Iterator[np.ndarray]:
    index = 0
    while True:
        yield synthetic_frame(index, seed)
        index += 1


def folder_source(path: str) -> Iterator[np.ndarray]:
    files = sorted(p for p in Path(path).iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not files:
        raise FileNotFoundError(f"No image found in folder {path!r}")
    while True:
        for file in files:
            image = cv2.imread(str(file), cv2.IMREAD_COLOR)
            if image is None:
                log.warning("Cannot read image %s, skipped", file)
                continue
            yield image


def video_source(path: str) -> Iterator[np.ndarray]:
    if not Path(path).is_file():
        raise FileNotFoundError(f"Video file not found: {path!r}")
    while True:
        capture = cv2.VideoCapture(path)
        try:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Cannot read video {path!r}")
            while ok:
                yield frame
                ok, frame = capture.read()
        finally:
            capture.release()


def webcam_source(index: int = 0) -> Iterator[np.ndarray]:
    capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open webcam {index}")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Webcam {index} stopped sending frames")
            yield frame
    finally:
        capture.release()


def open_source(settings: Settings) -> Iterator[np.ndarray]:
    if settings.source == "synthetic":
        return synthetic_source(settings.synthetic_seed)
    if settings.source == "folder":
        return folder_source(settings.source_path)
    if settings.source == "video":
        return video_source(settings.source_path)
    if settings.source == "webcam":
        return webcam_source(settings.webcam_index)
    raise ValueError(f"Unknown source {settings.source!r}")
