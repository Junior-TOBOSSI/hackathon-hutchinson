"""Build the training dataset: SH17 with our 9 classes, hands and gloves merged into 'hand'.

Usage (from the repository root, ON THE MACHINE THAT TRAINS):
    python usecases/safety/notebooks/prepare_dataset.py
    python usecases/safety/notebooks/prepare_dataset.py --src data/raw/safety/sh17 \
        --out data/processed/safety/sh17_hand

Why merge hands + gloves: in SH17 a gloved hand is labelled ONLY 'gloves' and a bare hand
ONLY 'hands'. The model finds 84% of bare hands but misses 55% of gloves (5.6x fewer
examples). One 'hand' class lets every glove benefit from the 15,000 hand examples; a small
classifier then tells gloved from bare on the hand crop (separate step).

The source is never modified: images are RELATIVE symlinks, labels are new files.
Run this script on the training machine itself (copying symlinks to a USB key breaks them).
"""

from __future__ import annotations

import argparse
import os
import shutil
from collections import Counter
from pathlib import Path

import yaml
from explore_sh17 import SH17_DEFAULT_NAMES, Box, parse_label_file, read_splits  # same folder

# New class list. ORDER MATTERS: it defines the class ids of the trained model.
NEW_NAMES = ["person", "head", "face", "helmet", "vest", "glasses", "hand", "shoes", "foot"]
# SH17 name -> new name. SH17 classes not listed here are dropped (ears, masks, tools, suits).
SH17_TO_NEW = {
    "person": "person",
    "head": "head",
    "face": "face",  # kept: needed to hide faces
    "helmet": "helmet",
    "safety-vest": "vest",
    "glasses": "glasses",
    "hands": "hand",
    "gloves": "hand",
    "shoes": "shoes",
    "foot": "foot",
}
SAME_OBJECT_IOU = 0.7  # after merging, a hand labelled twice (hands + gloves) is kept once


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a.cx - a.w / 2, a.cy - a.h / 2, a.cx + a.w / 2, a.cy + a.h / 2
    bx1, by1, bx2, by2 = b.cx - b.w / 2, b.cy - b.h / 2, b.cx + b.w / 2, b.cy + b.h / 2
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def remap(boxes: list[Box], old_to_new: dict[int, int]) -> tuple[list[Box], int]:
    """Keep our classes with their new ids; drop duplicates created by the merge."""
    hand = NEW_NAMES.index("hand")
    kept: list[Box] = []
    merged_duplicates = 0
    for box in boxes:
        if box.cls not in old_to_new:
            continue
        new = Box(old_to_new[box.cls], box.cx, box.cy, box.w, box.h)
        # Only the merged class can hold the same object twice (once 'hands', once 'gloves').
        # Two persons standing close together are two real objects: never removed.
        if new.cls == hand and any(k.cls == hand and iou(k, new) >= SAME_OBJECT_IOU for k in kept):
            merged_duplicates += 1
            continue
        kept.append(new)
    return kept, merged_duplicates


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, default=Path("data/raw/safety/sh17"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/safety/sh17_hand"))
    args = parser.parse_args(argv)

    # SH17 has no YAML: class ids follow the official weights (checked against voc_labels).
    old_to_new = {
        SH17_DEFAULT_NAMES.index(old): NEW_NAMES.index(new) for old, new in SH17_TO_NEW.items()
    }
    splits = read_splits(args.src)
    images = {p.stem: p for p in (args.src / "images").iterdir()}

    shutil.rmtree(args.out, ignore_errors=True)
    (args.out / "images").mkdir(parents=True)
    (args.out / "labels").mkdir()
    counts: dict[str, Counter] = {s: Counter() for s in splits}
    stats = Counter()
    for split, stems in splits.items():
        lines = []
        for stem in sorted(stems):
            label = args.src / "labels" / f"{stem}.txt"
            if stem not in images or not label.exists():
                stats["skipped_missing"] += 1
                continue
            boxes, issues = parse_label_file(label, len(SH17_DEFAULT_NAMES))
            stats.update(issues)
            boxes, duplicates = remap(boxes, old_to_new)
            stats["merged_duplicates"] += duplicates
            # An image with none of our classes stays: it teaches "nothing to detect here".
            image = images[stem]
            link = args.out / "images" / image.name
            link.symlink_to(os.path.relpath(image.resolve(), link.parent.resolve()))
            (args.out / "labels" / f"{stem}.txt").write_text(
                "".join(b.to_line() + "\n" for b in boxes)
            )
            counts[split].update(NEW_NAMES[b.cls] for b in boxes)
            lines.append(f"./images/{image.name}")
        (args.out / f"{split}.txt").write_text("\n".join(lines) + "\n")
        print(f"{split}: {len(lines)} images")

    # 'path' is rewritten to an absolute path by train_detector.py on the training machine.
    data = {"path": str(args.out.resolve()), "train": "train.txt", "val": "val.txt"}
    data["names"] = dict(enumerate(NEW_NAMES))
    (args.out / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False))

    print(f"\n{'class':<8}" + "".join(f"{s:>8}" for s in counts))
    for name in NEW_NAMES:
        print(f"{name:<8}" + "".join(f"{counts[s][name]:>8}" for s in counts))
    print(f"\ncorrections: {dict(stats)}")
    print(f"dataset written to {args.out}")


if __name__ == "__main__":
    main()
