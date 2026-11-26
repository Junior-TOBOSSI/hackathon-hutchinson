"""Turn a screenshot of the client's current vision system into a clean reference image.

    python -m usecases.workstation.clean_capture --input <capture.png> --out <reference.png>

The screenshot contains, on top of the camera image:
- green banners ("CAM 1 OK", "ALL ZONES OK") and a frame around the video,
- drawn overlays INSIDE the video: magenta "operator spot" box and label, green zone box
  and its dot, a purple player dot, white text (fps, latency), a white cross and the mouse
  cursor captured with the screen.

Steps:
1. CROP: find the green frame (banner colour) and keep the video area inside it.
2. MASK: pixels of the overlays, found by their saturated colours (magenta, purple, bright
   green), plus the white pixels inside the known text / cursor rectangles.
3. INPAINT: fill the masked pixels from their surroundings (OpenCV Telea). Overlays are
   thin lines and text, which inpainting erases well.

The text rectangles are specific to this capture of the old system (normalized
coordinates of the video area): adapt ``WHITE_OVERLAYS`` for another capture.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

# Banner / frame green of the old system (HSV, OpenCV ranges: H 0-179).
BANNER_GREEN = ((45, 120, 60), (80, 255, 200))
# Overlay colours drawn inside the video.
OVERLAY_COLOURS = {
    "magenta_and_purple": ((125, 90, 90), (172, 255, 255)),
    "bright_green": ((40, 120, 100), (85, 255, 255)),
}
# White overlays (text, cross, cursor): x1, y1, x2, y2 normalized in the video area.
WHITE_OVERLAYS = {
    "status_text": (0.0, 0.90, 0.68, 1.0),
    "cross": (0.455, 0.0, 0.49, 0.08),
    "mouse_cursor": (0.40, 0.36, 0.43, 0.44),
}
BORDER = 3  # pixels removed on each side of the video area (anti-aliased frame edge)


def find_video_area(image: np.ndarray) -> tuple[int, int, int, int]:
    """(x1, y1, x2, y2) of the video inside the green frame; whole image if no frame."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, *BANNER_GREEN) > 0
    if green.mean() < 0.02:
        return 0, 0, image.shape[1], image.shape[0]
    ys, xs = np.nonzero(green)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    panel = green[y0:y1, x0:x1]
    rows = np.nonzero(panel.mean(axis=1) < 0.5)[0]  # rows that are not banner
    cols = np.nonzero(panel.mean(axis=0) < 0.5)[0]
    if len(rows) == 0 or len(cols) == 0:
        return 0, 0, image.shape[1], image.shape[0]
    return (
        int(x0 + cols.min() + BORDER),
        int(y0 + rows.min() + BORDER),
        int(x0 + cols.max() + 1 - BORDER),
        int(y0 + rows.max() + 1 - BORDER),
    )


def overlay_mask(video: np.ndarray) -> np.ndarray:
    """uint8 mask (255 = overlay pixel) of the drawn overlays inside the video area."""
    h, w = video.shape[:2]
    hsv = cv2.cvtColor(video, cv2.COLOR_BGR2HSV)
    mask = np.zeros((h, w), np.uint8)
    for low, high in OVERLAY_COLOURS.values():
        mask |= cv2.inRange(hsv, low, high)
    white = cv2.inRange(hsv, (0, 0, 190), (179, 60, 255))
    for x1, y1, x2, y2 in WHITE_OVERLAYS.values():
        box = (slice(int(y1 * h), int(y2 * h)), slice(int(x1 * w), int(x2 * w)))
        mask[box] |= white[box]
    # Grow the mask: the anti-aliased edges of lines and letters must go too.
    return cv2.dilate(mask, np.ones((5, 5), np.uint8))


def clean_capture(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (clean reference image, overlay mask used) for a screenshot."""
    x1, y1, x2, y2 = find_video_area(image)
    video = image[y1:y2, x1:x2].copy()
    mask = overlay_mask(video)
    return cv2.inpaint(video, mask, 5, cv2.INPAINT_TELEA), mask


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    image = cv2.imread(str(Path(args.input).expanduser()))
    if image is None:
        raise SystemExit(f"Cannot read {args.input}")
    clean, mask = clean_capture(image)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), clean)
    cv2.imwrite(str(out.with_name(out.stem + "_overlay_mask.png")), mask)
    print(f"Clean reference: {out} ({clean.shape[1]}x{clean.shape[0]})")
    print(f"Erased pixels  : {(mask > 0).mean():.1%} of the video area")


if __name__ == "__main__":
    main()
