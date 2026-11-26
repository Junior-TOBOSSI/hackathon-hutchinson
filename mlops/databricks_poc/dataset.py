"""DBX-00B: reproducible SYNTHETIC image dataset (nothing related to a real product).

    python -m mlops.databricks_poc.dataset

- 200 grayscale PNG images, 64 x 64 px, seed 2026.
- OK  : a complete square outline.
- NOK : the same square with a gap in one side, or a deformed (skewed) outline.
- Controlled variations: position offset, brightness, Gaussian noise, line thickness.
- Stratified split 60 / 20 / 20 (train 120, validation 40, test 40).
- manifest.json: label, split, variation parameters and SHA-256 of every file.

``render()`` is also used to create shifted images for the drift scenario.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from mlops.databricks_poc.common import DATASET_VERSION, LOCAL_DATASET

SEED = 2026
SIZE = 64
PER_CLASS = 100
SPLITS = {"train": 0.6, "validation": 0.2, "test": 0.2}


def render(
    label: str,
    rng: np.random.Generator,
    brightness: float | None = None,
    noise: float | None = None,
) -> tuple[Image.Image, dict]:
    """Draw one image; returns the image and the variation parameters actually used."""
    params = {
        "dx": int(rng.integers(-6, 7)),
        "dy": int(rng.integers(-6, 7)),
        "side": int(rng.integers(26, 36)),
        "thickness": int(rng.integers(2, 4)),
        "background": int(rng.integers(30, 60)),
        "brightness": float(brightness if brightness is not None else rng.uniform(0.75, 1.0)),
        "noise": float(noise if noise is not None else rng.uniform(4.0, 12.0)),
        "defect": None,
    }
    image = Image.new("L", (SIZE, SIZE), params["background"])
    draw = ImageDraw.Draw(image)
    half = params["side"] // 2
    cx, cy = SIZE // 2 + params["dx"], SIZE // 2 + params["dy"]
    corners = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]
    ink = int(255 * params["brightness"])
    if label == "NOK":
        params["defect"] = str(rng.choice(["gap", "skew"]))
        if params["defect"] == "skew":
            shift = int(rng.integers(6, 11)) * int(rng.choice([-1, 1]))
            corners[0] = (corners[0][0] + shift, corners[0][1])
            corners[1] = (corners[1][0] + shift, corners[1][1])
    edges = list(zip(corners, corners[1:] + corners[:1], strict=True))
    gap_edge = int(rng.integers(0, 4)) if params["defect"] == "gap" else None
    for index, (start, end) in enumerate(edges):
        if index == gap_edge:
            # Draw the edge in two pieces, leaving a hole of ~35 % in the middle.
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            cut = 0.18
            a = (
                start[0] + (mx - start[0]) * (1 - cut * 2),
                start[1] + (my - start[1]) * (1 - cut * 2),
            )
            b = (end[0] + (mx - end[0]) * (1 - cut * 2), end[1] + (my - end[1]) * (1 - cut * 2))
            draw.line([start, a], fill=ink, width=params["thickness"])
            draw.line([b, end], fill=ink, width=params["thickness"])
        else:
            draw.line([start, end], fill=ink, width=params["thickness"])
    pixels = np.asarray(image, dtype=np.float32) + rng.normal(0, params["noise"], (SIZE, SIZE))
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="L"), params


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(out: Path = LOCAL_DATASET) -> dict:
    rng = np.random.default_rng(SEED)
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for label in ("OK", "NOK"):
        order = rng.permutation(PER_CLASS)
        n_train, n_val = int(PER_CLASS * SPLITS["train"]), int(PER_CLASS * SPLITS["validation"])
        for index in range(PER_CLASS):
            rank = int(np.where(order == index)[0][0])
            split = (
                "train" if rank < n_train else "validation" if rank < n_train + n_val else "test"
            )
            image, params = render(label, rng)
            name = f"{split}/{label}/{label.lower()}_{index:03d}.png"
            path = out / name
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, format="PNG")
            items.append(
                {"file": name, "label": label, "split": split, "sha256": sha256(path), **params}
            )
    manifest = {
        "dataset_version": DATASET_VERSION,
        "synthetic": True,
        "description": "Synthetic squares: OK = complete outline, NOK = gap or skewed outline.",
        "generator": "mlops/databricks_poc/dataset.py",
        "seed": SEED,
        "image_size": [SIZE, SIZE],
        "mode": "L (grayscale)",
        "classes": ["OK", "NOK"],
        "split_ratios": SPLITS,
        "counts": {
            split: {
                lab: sum(1 for i in items if i["split"] == split and i["label"] == lab)
                for lab in ("OK", "NOK")
            }
            for split in SPLITS
        },
        "items": items,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    manifest = generate()
    print(f"{len(manifest['items'])} images in {LOCAL_DATASET}")
    print("counts:", manifest["counts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
