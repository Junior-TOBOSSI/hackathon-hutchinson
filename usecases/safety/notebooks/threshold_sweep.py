"""Precision and recall of each class for several confidence thresholds (choose class_conf).

The model runs ONCE on the images at a very low threshold; every threshold is then computed
from the same detections. A detection is correct when it matches an annotated box of the same
class with IoU >= 0.5 (each annotated box matched at most once, most confident first).

    python usecases/safety/notebooks/threshold_sweep.py                     # validation, YOLO26s
    python usecases/safety/notebooks/threshold_sweep.py --split test        # final check only

Choose the thresholds on the VALIDATION split, then check them once on the test split.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
THRESHOLDS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
SHOWN = ("helmet", "glasses", "gloves", "shoes", "hands", "head", "face")
FR = {"helmet": "Casque", "glasses": "Lunettes", "gloves": "Gants", "shoes": "Chaussures",
      "hands": "Mains", "head": "Tête", "face": "Visage"}  # fmt: skip


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU of one box a (x1, y1, x2, y2) with each box of b (n, 4)."""
    x1, y1 = np.maximum(a[0], b[:, 0]), np.maximum(a[1], b[:, 1])
    x2, y2 = np.minimum(a[2], b[:, 2]), np.minimum(a[3], b[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (a[2] - a[0]) * (a[3] - a[1]) + (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]) - inter
    return inter / np.maximum(area, 1e-9)


def ground_truth(label: Path) -> list[tuple[int, np.ndarray]]:
    boxes = []
    if label.is_file():
        for line in label.read_text().split("\n"):
            if line.strip():
                c, cx, cy, w, h = map(float, line.split()[:5])
                boxes.append((int(c), np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])))
    return boxes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", default="data/models/safety/sh17_ours_yolo26s_640.pt")
    parser.add_argument("--dataset", type=Path, default=Path("data/processed/safety/sh17_ours"))
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)
    os.environ.setdefault("YOLO_OFFLINE", "1")
    from ultralytics import YOLO

    model = YOLO(str(REPO / args.weights))
    names = {i: str(n).lower() for i, n in model.names.items()}
    root = REPO / args.dataset
    images = [
        line.strip()
        for line in (root / f"{args.split}.txt").read_text().split("\n")
        if line.strip()
    ]

    # per class: list of (confidence, is_correct) and number of annotated boxes
    scored: dict[str, list[tuple[float, bool]]] = {n: [] for n in names.values()}
    annotated: dict[str, int] = {n: 0 for n in names.values()}
    for k, rel in enumerate(images, 1):
        path = root / rel
        gt = ground_truth(root / "labels" / (Path(rel).stem + ".txt"))
        for c, _ in gt:
            annotated[names[c]] += 1
        result = model.predict(
            str(path), conf=0.05, imgsz=args.imgsz, device=args.device, verbose=False
        )[0]
        boxes = result.boxes
        preds = zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxyn.tolist(), strict=True)
        preds = sorted(preds, key=lambda p: -p[1])
        used = set()
        for c, conf, box in preds:
            same = [(i, b) for i, (gc, b) in enumerate(gt) if gc == int(c) and i not in used]
            hit = False
            if same:
                overlaps = iou(np.array(box), np.stack([b for _, b in same]))
                j = int(overlaps.argmax())
                if overlaps[j] >= 0.5:
                    used.add(same[j][0])
                    hit = True
            scored[names[int(c)]].append((conf, hit))
        if k % 100 == 0:
            print(f"  {k}/{len(images)} images")

    print(f"\n{args.weights} · {args.split} · {len(images)} images · {args.imgsz} px")
    print(f"{'Classe':<11}" + "".join(f"  seuil {t:.2f}     " for t in THRESHOLDS))
    for name in SHOWN:
        row = f"{FR[name]:<11}"
        for t in THRESHOLDS:
            kept = [hit for conf, hit in scored[name] if conf >= t]
            tp = sum(kept)
            p = tp / len(kept) if kept else 0.0
            r = tp / annotated[name] if annotated[name] else 0.0
            row += f"  P {p:.2f} R {r:.2f}  "
        print(row + f"  ({annotated[name]} annotés)")


if __name__ == "__main__":
    main()
