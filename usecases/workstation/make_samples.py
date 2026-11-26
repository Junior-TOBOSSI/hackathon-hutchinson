"""Generate SYNTHETIC top-view images of a workstation, to test before the real camera.

    python -m usecases.workstation.make_samples [--out data/processed/workstation/synthetic]

Writes (never versioned, data/ is ignored by Git):
- reference.png  : the tidy station, the keep-clear zone empty
- scenarios/     : one image per situation, named after the expected outcome
- sequence/      : a short "film" (one image every 0.5 s at PIPELINE_FPS=2) for the
                   folder source of the platform: SOURCE=folder SOURCE_PATH=.../sequence

The drawn shapes are NOT recognised by a COCO model (they are simple shapes): these images
test the reference-difference layer, the zone geometry and the persistence. To test the
detector, take real photos with the webcam (see README.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

H, W = 720, 1280
# The keep-clear zone, normalized. The same polygon is the default in config.yaml.
KEEP_CLEAR = [(0.62, 0.55), (0.95, 0.55), (0.95, 0.95), (0.62, 0.95)]


def _px(x: float, y: float) -> tuple[int, int]:
    return int(x * W), int(y * H)


def station(seed: int = 0) -> np.ndarray:
    """The tidy station, seen from above."""
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), (150, 160, 165), np.uint8)  # grey bench (BGR)
    # Slight texture so that the bench is not perfectly flat.
    texture = rng.normal(0, 4, (H, W, 1)).astype(np.int16)
    img = np.clip(img.astype(np.int16) + texture, 0, 255).astype(np.uint8)

    # Shadow board on the left: outlines + tools in place.
    cv2.rectangle(img, _px(0.03, 0.05), _px(0.40, 0.48), (90, 90, 95), -1)
    wrench(img, 0.08, 0.12)
    cv2.rectangle(img, _px(0.25, 0.10), _px(0.36, 0.40), (40, 40, 200), -1)  # caliper (red)
    # Parts tray, bottom left.
    cv2.rectangle(img, _px(0.05, 0.60), _px(0.35, 0.92), (30, 110, 30), -1)
    cv2.rectangle(img, _px(0.07, 0.63), _px(0.33, 0.89), (50, 140, 50), -1)
    # Work area in the middle (where the part is handled).
    cv2.rectangle(img, _px(0.42, 0.20), _px(0.58, 0.80), (170, 180, 185), -1)
    # Keep-clear zone, bottom right: yellow / black tape on its border.
    pts = np.array([_px(*p) for p in KEEP_CLEAR], np.int32)
    cv2.polylines(img, [pts], True, (0, 220, 240), 8)
    return img


def wrench(img: np.ndarray, x: float, y: float, angle: float = 0.0) -> None:
    """A flat wrench: a handle and two jaws, rotated by ``angle`` degrees."""
    cx, cy = _px(x + 0.06, y + 0.15)
    shape = np.zeros_like(img)
    cv2.rectangle(shape, (cx - 15, cy - 110), (cx + 15, cy + 110), (200, 200, 200), -1)
    cv2.circle(shape, (cx, cy - 115), 35, (200, 200, 200), -1)
    cv2.circle(shape, (cx, cy + 115), 30, (200, 200, 200), -1)
    rot = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    shape = cv2.warpAffine(shape, rot, (W, H))
    img[shape.any(axis=2)] = shape[shape.any(axis=2)]


def cup(img: np.ndarray, x: float, y: float) -> None:
    cv2.circle(img, _px(x, y), 55, (40, 60, 160), -1)
    cv2.circle(img, _px(x, y), 40, (20, 30, 90), -1)


def box(img: np.ndarray, x: float, y: float, w: float = 0.10, h: float = 0.14) -> None:
    cv2.rectangle(img, _px(x, y), _px(x + w, y + h), (60, 120, 200), -1)


def arm(img: np.ndarray, tip_x: float, tip_y: float) -> None:
    """An arm reaching from the bottom edge to (tip_x, tip_y)."""
    skin = (120, 160, 210)
    cv2.line(img, _px(tip_x + 0.05, 1.05), _px(tip_x, tip_y), skin, 70)
    cv2.circle(img, _px(tip_x, tip_y), 45, skin, -1)


def noise(img: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(img.astype(np.int16) + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)


def without_tool(img: np.ndarray) -> np.ndarray:
    """Remove the wrench from the shadow board (paint the board back)."""
    out = img.copy()
    cv2.rectangle(out, _px(0.04, 0.055), _px(0.22, 0.475), (90, 90, 95), -1)
    return out


def scenarios() -> dict[str, np.ndarray]:
    ref = station()
    out: dict[str, np.ndarray] = {}

    out["01_conforme_noise"] = noise(ref, 1)
    out["02_conforme_lighting"] = np.clip(ref.astype(np.int16) + 35, 0, 255).astype(np.uint8)

    img = noise(ref, 2)
    box(img, 0.20, 0.50)  # object on the bench but OUTSIDE the zone
    out["03_conforme_object_outside_zone"] = img

    img = noise(ref, 3)
    cup(img, 0.78, 0.75)
    out["04_anomalie_cup_in_zone"] = img

    img = noise(ref, 4)
    box(img, 0.72, 0.65)
    out["05_anomalie_box_in_zone"] = img

    img = noise(without_tool(ref), 5)
    wrench(img, 0.75, 0.58, angle=90)  # the wrench was left in the zone
    out["06_anomalie_tool_left_in_zone"] = img

    img = noise(ref, 6)
    box(img, 0.57, 0.70, w=0.10, h=0.12)  # half inside, half outside
    out["07_anomalie_object_across_border"] = img

    img = noise(ref, 7)
    arm(img, 0.80, 0.70)
    out["08_a_trancher_hand_held_in_zone"] = img
    return out


def sequence() -> list[np.ndarray]:
    """20 s at 2 images/s: tidy, a hand passes, tidy, a cup is put down and stays, removed."""
    ref = station()
    frames = []
    for i in range(40):
        img = noise(ref, 100 + i)
        if i in (8, 9):  # hand passing for 1 s: must NOT raise an alert
            arm(img, 0.80, 0.72)
        if 16 <= i < 30:  # cup put down for 7 s: alert after the persistence delay
            cup(img, 0.80, 0.75)
        frames.append(img)
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/processed/workstation/synthetic")
    out = Path(parser.parse_args().out).expanduser()
    (out / "scenarios").mkdir(parents=True, exist_ok=True)
    (out / "sequence").mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(out / "reference.png"), station())
    for name, img in scenarios().items():
        cv2.imwrite(str(out / "scenarios" / f"{name}.png"), img)
    for i, img in enumerate(sequence()):
        cv2.imwrite(str(out / "sequence" / f"{i:03d}.png"), img)
    print(f"Written to {out}: reference.png, scenarios/, sequence/")
    print("Keep-clear zone (normalized):", KEEP_CLEAR)


if __name__ == "__main__":
    main()
