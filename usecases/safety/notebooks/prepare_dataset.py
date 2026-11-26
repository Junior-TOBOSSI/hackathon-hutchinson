"""Build a training dataset from SH17, with one of three class sets (--mode).

Usage (from the repository root, ON THE MACHINE THAT TRAINS):
    python usecases/safety/notebooks/prepare_dataset.py --mode all   # A: 17 SH17 classes
    python usecases/safety/notebooks/prepare_dataset.py --mode ours  # B: our 9 classes
    python usecases/safety/notebooks/prepare_dataset.py --mode hand  # C: B, hands+gloves merged

Modes:
- all  : every SH17 class, unchanged (reference experiment).
- ours : only what the safety use case needs; 'hands' (bare hand) and 'gloves' (gloved hand)
         stay SEPARATE. A vs B changes only the class set: a fair comparison.
- hand : like 'ours' but hands + gloves merged into one 'hand' class. In SH17 a gloved hand
         is labelled ONLY 'gloves', a bare hand ONLY 'hands'; gloves have 5.6x fewer examples
         and are missed 55% of the time. Merging lets gloves benefit from the hand examples;
         a classifier on the hand crop would then tell gloved from bare (separate step).

Every mode applies the same corrections (boxes clipped to the image, invalid lines dropped)
and the same split. Output: data/processed/safety/sh17_<mode>/.

Split: SH17 only has train (6,479) / val (1,620). The validation picks the best epoch, so its
score is slightly optimistic. The SH17 val is therefore cut in two, at random with a FIXED
seed (same cut for every mode): val (picks the epoch) and test (final number, used once).
The official SH17 weights never saw any of these 1,620 images: they can be compared to our
models on the same test images.
The source is never modified: images are RELATIVE symlinks, labels are new files.
Run this script on the training machine itself (copying symlinks to a USB key breaks them).
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
from collections import Counter
from pathlib import Path

import yaml
from explore_sh17 import SH17_DEFAULT_NAMES, Box, parse_label_file, read_splits  # same folder

# For each mode: SH17 name -> new name. ORDER MATTERS: the order of first appearance of the
# new names defines the class ids of the trained model. SH17 classes not listed are dropped.
# Our PPE (helmet, glasses, gloves, shoes) + what the system needs around them:
# person (one result per person, contract), face (to hide faces), and head / hands / foot as
# EVIDENCE of absence: "bare hand visible" -> gloves absent; no hand visible -> uncertain.
OURS = {
    "person": "person",
    "face": "face",
    "helmet": "helmet",
    "glasses": "glasses",
    "gloves": "gloves",
    "shoes": "shoes",
    "head": "head",
    "hands": "hands",
    "foot": "foot",
}
MODES = {
    "all": {name: name for name in SH17_DEFAULT_NAMES},
    "ours": OURS,
    "hand": {**OURS, "gloves": "hand", "hands": "hand"},
}
SAME_OBJECT_IOU = 0.7  # after merging, a hand labelled twice (hands + gloves) is kept once
SPLIT_SEED = 0  # never change it once results are reported: the test set would change


def split_val_test(splits: dict[str, set[str]], test_fraction: float) -> dict[str, set[str]]:
    """Move a fixed random part of the SH17 'val' split into a new 'test' split."""
    if test_fraction <= 0 or "test" in splits:
        return splits
    val = sorted(splits["val"])  # sorted first: same result on every machine
    random.Random(SPLIT_SEED).shuffle(val)
    n_test = round(len(val) * test_fraction)
    return {**splits, "val": set(val[n_test:]), "test": set(val[:n_test])}


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a.cx - a.w / 2, a.cy - a.h / 2, a.cx + a.w / 2, a.cy + a.h / 2
    bx1, by1, bx2, by2 = b.cx - b.w / 2, b.cy - b.h / 2, b.cx + b.w / 2, b.cy + b.h / 2
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def remap(
    boxes: list[Box], old_to_new: dict[int, int], merged: int | None
) -> tuple[list[Box], int]:
    """Keep the mode's classes with their new ids; drop duplicates created by a merge."""
    kept: list[Box] = []
    merged_duplicates = 0
    for box in boxes:
        if box.cls not in old_to_new:
            continue
        new = Box(old_to_new[box.cls], box.cx, box.cy, box.w, box.h)
        # Only a merged class can hold the same object twice (once 'hands', once 'gloves').
        # Two persons standing close together are two real objects: never removed.
        if new.cls == merged and any(
            k.cls == merged and iou(k, new) >= SAME_OBJECT_IOU for k in kept
        ):
            merged_duplicates += 1
            continue
        kept.append(new)
    return kept, merged_duplicates


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=sorted(MODES), default="ours")
    parser.add_argument("--src", type=Path, default=Path("data/raw/safety/sh17"))
    parser.add_argument("--out", type=Path, default=None, help="default: .../sh17_<mode>")
    parser.add_argument(
        "--test-fraction", type=float, default=0.5, help="part of SH17 val used as test"
    )
    args = parser.parse_args(argv)
    out = args.out or Path(f"data/processed/safety/sh17_{args.mode}")

    # SH17 has no YAML: class ids follow the official weights (checked against voc_labels).
    mapping = MODES[args.mode]
    new_names = list(dict.fromkeys(mapping.values()))
    old_to_new = {SH17_DEFAULT_NAMES.index(o): new_names.index(n) for o, n in mapping.items()}
    merged = new_names.index("hand") if "hand" in new_names else None

    splits = split_val_test(read_splits(args.src), args.test_fraction)
    images = {p.stem: p for p in (args.src / "images").iterdir()}
    shutil.rmtree(out, ignore_errors=True)
    (out / "images").mkdir(parents=True)
    (out / "labels").mkdir()
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
            boxes, duplicates = remap(boxes, old_to_new, merged)
            stats["merged_duplicates"] += duplicates
            # An image with none of the classes stays: it teaches "nothing to detect here".
            image = images[stem]
            link = out / "images" / image.name
            link.symlink_to(os.path.relpath(image.resolve(), link.parent.resolve()))
            (out / "labels" / f"{stem}.txt").write_text("".join(b.to_line() + "\n" for b in boxes))
            counts[split].update(new_names[b.cls] for b in boxes)
            lines.append(f"./images/{image.name}")
        (out / f"{split}.txt").write_text("\n".join(lines) + "\n")
        print(f"{split}: {len(lines)} images")

    # 'path' is rewritten to an absolute path by train_detector.py on the training machine.
    data = {"path": str(out.resolve()), **{s: f"{s}.txt" for s in ("train", "val", "test")}}
    if "test" not in splits:
        del data["test"]
    data["names"] = dict(enumerate(new_names))
    (out / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False))

    print(f"\nmode '{args.mode}': {len(new_names)} classes")
    print(f"{'class':<18}" + "".join(f"{s:>8}" for s in counts))
    for name in new_names:
        print(f"{name:<18}" + "".join(f"{counts[s][name]:>8}" for s in counts))
    print(f"\ncorrections: {dict(stats)}")
    print(f"dataset written to {out}")


if __name__ == "__main__":
    main()
