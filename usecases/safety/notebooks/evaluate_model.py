"""Measure the SH17 PPE model per class, to tell a model weakness from a camera problem.

Usage (from the repository root, venv activated):
    # B. Reference: random images of the SH17 validation split (never seen in training)
    python usecases/safety/notebooks/evaluate_model.py --n 300
    # C. Our own pictures (no labels needed): annotated previews, faces hidden
    python usecases/safety/notebooks/evaluate_model.py --images data/raw/safety/webcam

Reading the result:
- gloves/shoes good on SH17 but bad on our camera -> camera / framing / domain problem;
- gloves/shoes bad on SH17 too                    -> model weakness: retrain or bigger model.

Nothing is written in data/raw/ (read-only by convention): the subset is built with
symlinks in the output folder, where Ultralytics also writes its label cache.
Every saved preview has faces pixelated (same code as webcam_preview.py).
"""

from __future__ import annotations

import argparse
import random
import shutil
from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO
from webcam_preview import PRIVACY_CONF, draw, hide_faces  # same folder

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
# Our PPE classes and the body parts used as evidence, with their SH17 names.
# SH17 names and our retrained model names (vest, hand); classes unknown to the model are skipped.
REPORTED_CLASSES = [
    "person", "helmet", "safety-vest", "vest", "glasses", "gloves", "hand", "shoes", "head",
    "hands", "foot",
]  # fmt: skip


def build_subset(dataset: Path, split: str, n: int, seed: int, out: Path) -> Path:
    """Pick n random images of a split; link them with their labels into out/subset."""
    # SH17 lists are 'val_files.txt'; the prepared dataset (prepare_dataset.py) uses 'val.txt'.
    list_file = dataset / f"{split}_files.txt"
    if not list_file.exists():
        list_file = dataset / f"{split}.txt"
    listed = list_file.read_text(encoding="utf-8").split()
    names = sorted(Path(line.replace("\\", "/")).name for line in listed)
    random.Random(seed).shuffle(names)
    names = names[:n]

    subset = out / "subset"
    shutil.rmtree(subset, ignore_errors=True)
    (subset / "images").mkdir(parents=True)
    (subset / "labels").mkdir()
    for name in names:
        (subset / "images" / name).symlink_to((dataset / "images" / name).resolve())
        label = dataset / "labels" / f"{Path(name).stem}.txt"
        if label.exists():
            shutil.copy(label, subset / "labels" / label.name)
    # Unresolved paths: Ultralytics must find the labels next to the LINK, in out/subset.
    image_list = out / "subset.txt"
    image_list.write_text("\n".join(str(subset.resolve() / "images" / n) for n in names) + "\n")
    print(f"{len(names)} images taken from {split}_files.txt (seed {seed})")
    return image_list


def count_instances(label_dir: Path) -> Counter:
    counts: Counter = Counter()
    for path in label_dir.glob("*.txt"):
        counts.update(int(line.split()[0]) for line in path.read_text().splitlines() if line)
    return counts


def evaluate(model: YOLO, image_list: Path, out: Path, imgsz: int) -> None:
    """Run the official Ultralytics validation and print our classes only."""
    data_yaml = out / "data.yaml"
    names = "\n".join(f"  {i}: {n}" for i, n in model.names.items())
    # Ultralytics requires a 'train' key even to validate: it is not used here.
    data_yaml.write_text(
        f"path: {out.resolve()}\ntrain: {image_list.name}\nval: {image_list.name}\n"
        f"names:\n{names}\n"
    )
    metrics = model.val(
        data=str(data_yaml), split="val", imgsz=imgsz, batch=8, device="cpu",
        plots=False, project=str(out.resolve()), name="val", exist_ok=True, verbose=False,
    )  # fmt: skip

    instances = count_instances(out / "subset" / "labels")
    ids = {str(n).lower(): i for i, n in model.names.items()}
    evaluated = list(metrics.box.ap_class_index)
    print(f"\n{'class':<12} {'objects':>8} {'precision':>10} {'recall':>8} {'mAP50':>7}")
    for name in REPORTED_CLASSES:
        cid = ids.get(name)
        if cid is None:
            continue  # class not in this model
        if cid not in evaluated:
            print(f"{name:<12} {instances.get(cid, 0):>8}   (no object of this class here)")
            continue
        p, r, ap50, _ = metrics.box.class_result(evaluated.index(cid))
        print(f"{name:<12} {instances[cid]:>8} {p:>10.2f} {r:>8.2f} {ap50:>7.2f}")
    print(f"{'ALL 17':<12} {sum(instances.values()):>8} {metrics.box.mp:>10.2f}"
          f" {metrics.box.mr:>8.2f} {metrics.box.map50:>7.2f}")  # fmt: skip
    print("\nrecall = share of real objects found ; precision = share of detections that are right")


def save_previews(model: YOLO, images: list[Path], out_dir: Path, imgsz: int, conf: float):
    """Draw the predictions with faces pixelated; return the count of each class seen."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = {i: str(n).lower() for i, n in model.names.items()}
    seen: Counter = Counter()
    for path in images:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        scale = 1280 / max(image.shape[:2])
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        result = model.predict(image, conf=PRIVACY_CONF, imgsz=imgsz, device="cpu", verbose=False)
        boxes = result[0].boxes
        detections = [
            (names[int(c)], float(s), tuple(int(v) for v in xyxy))
            for c, s, xyxy in zip(boxes.cls, boxes.conf, boxes.xyxy, strict=True)
        ]
        hide_faces(image, detections)  # always before saving
        seen.update(draw(image, detections, conf))
        cv2.imwrite(str(out_dir / f"{path.stem}.jpg"), image)
    print(f"{len(images)} previews (faces hidden) written to {out_dir}")
    return seen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", default="data/models/safety/sh17_yolov8s.pt")
    parser.add_argument("--dataset", type=Path, default=Path("data/raw/safety/sh17"))
    parser.add_argument("--split", default="val")
    parser.add_argument("--n", type=int, default=300, help="number of images to evaluate")
    parser.add_argument("--images", type=Path, help="folder of our own (unlabelled) pictures")
    parser.add_argument("--previews", type=int, default=10)
    parser.add_argument("--conf", type=float, default=0.25, help="threshold for previews")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("data/processed/safety/eval"))
    args = parser.parse_args(argv)

    model = YOLO(args.weights)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.images:  # C. our pictures: visual check, faces hidden
        images = sorted(p for p in args.images.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
        seen = save_previews(model, images, args.out / "own_previews", args.imgsz, args.conf)
        print("classes seen at threshold", args.conf, ":", dict(seen.most_common()))
        return
    image_list = build_subset(args.dataset, args.split, args.n, args.seed, args.out)  # B.
    evaluate(model, image_list, args.out, args.imgsz)
    sample = sorted((args.out / "subset" / "images").iterdir())[: args.previews]
    save_previews(model, sample, args.out / "sh17_previews", args.imgsz, args.conf)


if __name__ == "__main__":
    main()
