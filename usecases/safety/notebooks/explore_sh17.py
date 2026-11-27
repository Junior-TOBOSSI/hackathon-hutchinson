"""Explore, check and clean the SH17 PPE dataset (YOLO format) before training.

Usage (from the repository root):
    python usecases/safety/notebooks/explore_sh17.py data/raw/safety/sh17
    python usecases/safety/notebooks/explore_sh17.py data/raw/safety/sh17 \
        --fix data/processed/safety/sh17_clean

What it does:
1. Understand: class counts, box sizes, persons per image, PPE-to-person association.
2. Completeness: images without labels, labels without images, empty label files,
   images outside every split, images in two splits, persons with nothing annotated.
3. Quality: unreadable images, exact duplicate images, malformed / out-of-range /
   zero-size / duplicated / unknown-class annotation lines.
4. Previews: random images with boxes drawn, faces blurred, to check labels by eye.
5. --fix: writes a CLEANED COPY (labels + image symlinks + split lists). The original
   dataset is never modified.

Outputs go to data/processed/safety/sh17_report/ (git-ignored, stays on this machine).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}

# Class order of the official SH17 weights (read from yolo8n.pt), used only if no YAML file
# lists the names. Careful: the class list in the SH17 README is in a DIFFERENT order.
SH17_DEFAULT_NAMES = [
    "person", "ear", "ear-mufs", "face", "face-guard", "face-mask", "foot", "tool",
    "glasses", "gloves", "helmet", "hands", "head", "medical-suit", "shoes", "safety-suit",
    "safety-vest",
]  # fmt: skip

# Our PPE classes (left) and their SH17 name (right).
TARGET_CLASSES = {
    "person": "person",
    "helmet": "helmet",
    "vest": "safety-vest",
    "glasses": "glasses",
    "gloves": "gloves",
    "shoes": "shoes",
}
# Body parts: a visible head without helmet is evidence that the helmet is absent.
EVIDENCE_CLASSES = {"head": "head", "hands": "hands", "foot": "foot"}
FACE_CLASS = "face"

# Box size buckets, as a fraction of the image area.
SMALL_AREA, MEDIUM_AREA = 0.01, 0.05


@dataclass(frozen=True)
class Box:
    """One YOLO box: class id and center/size normalised to [0, 1]."""

    cls: int
    cx: float
    cy: float
    w: float
    h: float

    def contains_center_of(self, other: Box) -> bool:
        return (
            abs(other.cx - self.cx) <= self.w / 2 and abs(other.cy - self.cy) <= self.h / 2
        )

    def to_line(self) -> str:
        return f"{self.cls} {self.cx:.6f} {self.cy:.6f} {self.w:.6f} {self.h:.6f}"


# --------------------------------------------------------------------------- loading


def normalise_name(name: str) -> str:
    return str(name).strip().lower().replace("_", "-").replace(" ", "-")


def load_class_names(root: Path) -> list[str]:
    """Read class names from the first YAML file that has a 'names' key."""
    for path in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = data.get("names") if isinstance(data, dict) else None
        if isinstance(names, dict):  # {0: "person", 1: "head", ...}
            names = [names[k] for k in sorted(names, key=int)]
        if names:
            print(f"Class names read from {path}")
            return [normalise_name(n) for n in names]
    print("No YAML with class names found: using the class order of the SH17 weights.")
    return list(SH17_DEFAULT_NAMES)


def find_files(root: Path) -> tuple[list[Path], dict[str, Path]]:
    """All images, and label files (.txt inside a 'labels' folder) indexed by file stem."""
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS)
    labels = {p.stem: p for p in root.rglob("*.txt") if "labels" in p.parts}
    return images, labels


def read_splits(root: Path) -> dict[str, set[str]]:
    """Split lists such as train_files.txt / val_files.txt: split name -> image stems."""
    splits = {}
    for path in sorted(root.rglob("*.txt")):
        if "labels" in path.parts:
            continue
        name = path.stem.removesuffix("_files")
        if name in {"train", "val", "valid", "test"}:
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
            splits[name] = {Path(line.replace("\\", "/")).stem for line in lines if line}
    return splits


def inspect_image(path: Path) -> tuple[int, int] | None:
    """Return (width, height), or None if the image cannot be decoded."""
    try:
        from PIL import Image  # fast path: decodes JPEGs at 1/8 scale

        with Image.open(path) as image:
            size = image.size
            image.draft("L", (max(1, size[0] // 8), max(1, size[1] // 8)))
            image.load()  # raises on truncated / corrupt files
            return size
    except ImportError:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)  # slow fallback, full decode
        return None if image is None else (image.shape[1], image.shape[0])
    except Exception:
        return None


def parse_label_file(path: Path, n_classes: int) -> tuple[list[Box], Counter]:
    """Parse one YOLO label file. Returns the cleaned boxes and the problems found."""
    boxes: list[Box] = []
    issues: Counter = Counter()
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        try:
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(v) for v in parts[1:5])
        except (ValueError, IndexError):
            issues["malformed_line"] += 1
            continue
        if len(parts) != 5:
            issues["malformed_line"] += 1  # e.g. polygon instead of box
            continue
        if not 0 <= cls < n_classes:
            issues["unknown_class"] += 1
            continue
        if w <= 0 or h <= 0:
            issues["zero_size_box"] += 1
            continue
        # Clip boxes that go outside the image instead of throwing them away.
        x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
        x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
        if (x1, y1, x2, y2) != (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2):
            issues["out_of_image_clipped"] += 1
            if x2 <= x1 or y2 <= y1:
                issues["zero_size_box"] += 1
                continue
        box = Box(cls, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
        key = box.to_line()
        if key in seen:
            issues["duplicate_box"] += 1
            continue
        seen.add(key)
        boxes.append(box)
    return boxes, issues


# --------------------------------------------------------------------------- analysis


def scan(root: Path) -> dict:
    """Read every image and label once; collect everything the report needs."""
    names = load_class_names(root)
    images, labels = find_files(root)
    splits = read_splits(root)
    print(f"{len(images)} images, {len(labels)} label files, splits: {sorted(splits) or 'none'}")

    data = {
        "names": names,
        "splits": splits,
        "images": {},  # stem -> {"path", "size"}
        "boxes": {},  # stem -> list[Box], only for usable images
        "corrupt": [],
        "missing_label": [],
        "empty_label": [],
        "duplicates": [],  # (kept stem, dropped stem)
        "line_issues": Counter(),
        "orphan_labels": sorted(set(labels) - {p.stem for p in images}),
    }
    first_by_hash: dict[str, str] = {}
    for i, path in enumerate(images, start=1):
        if i % 500 == 0:
            print(f"  {i}/{len(images)} images checked...")
        stem = path.stem
        size = inspect_image(path)
        data["images"][stem] = {"path": path, "size": size}
        if size is None:
            data["corrupt"].append(stem)
            continue
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        if digest in first_by_hash:
            data["duplicates"].append((first_by_hash[digest], stem))
            continue
        first_by_hash[digest] = stem
        if stem not in labels:
            data["missing_label"].append(stem)
            continue
        boxes, issues = parse_label_file(labels[stem], len(names))
        data["line_issues"].update(issues)
        if not boxes:
            data["empty_label"].append(stem)
            continue
        data["boxes"][stem] = boxes
    return data


def class_id(names: list[str], name: str) -> int | None:
    return names.index(name) if name in names else None


def size_bucket(box: Box) -> str:
    area = box.w * box.h
    return "small" if area < SMALL_AREA else "medium" if area < MEDIUM_AREA else "large"


def count_bucket(n: int) -> str:
    return str(n) if n <= 2 else "3-5" if n <= 5 else "6+"


def percent(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def analyse(data: dict) -> dict:
    """Compute statistics on the usable images (readable, labelled, not duplicated)."""
    names, boxes_by_image = data["names"], data["boxes"]
    person_id = class_id(names, "person")
    watched = {**TARGET_CLASSES, **EVIDENCE_CLASSES}

    instances, images_with, sizes = Counter(), Counter(), defaultdict(Counter)
    inside_person, persons_per_image = Counter(), Counter()
    empty_persons = total_persons = 0
    for boxes in boxes_by_image.values():
        persons = [b for b in boxes if b.cls == person_id]
        others = [b for b in boxes if b.cls != person_id]
        persons_per_image[count_bucket(len(persons))] += 1
        for cls in {b.cls for b in boxes}:
            images_with[cls] += 1
        for b in boxes:
            instances[b.cls] += 1
            sizes[b.cls][size_bucket(b)] += 1
            if b.cls != person_id and any(p.contains_center_of(b) for p in persons):
                inside_person[b.cls] += 1
        for p in persons:
            total_persons += 1
            if not any(p.contains_center_of(o) for o in others):
                empty_persons += 1  # nothing annotated on this person: possibly incomplete

    per_class = []
    for ours, sh17 in watched.items():
        cid = class_id(names, sh17)
        if cid is None:
            per_class.append({"class": ours, "sh17_name": sh17, "missing_in_dataset": True})
            continue
        n = instances[cid]
        per_class.append({
            "class": ours,
            "sh17_name": sh17,
            "instances": n,
            "images": images_with[cid],
            "small_%": percent(sizes[cid]["small"], n),
            "medium_%": percent(sizes[cid]["medium"], n),
            "large_%": percent(sizes[cid]["large"], n),
            "inside_a_person_%": "-" if cid == person_id else percent(inside_person[cid], n),
        })  # fmt: skip

    # Split coverage and leakage (same image in two splits).
    split_counts, stems_seen = {}, Counter()
    for split, stems in data["splits"].items():
        usable = stems & boxes_by_image.keys()
        stems_seen.update(stems)
        counts = Counter(b.cls for s in usable for b in boxes_by_image[s])
        split_counts[split] = {"images": len(usable), **{
            ours: counts[class_id(names, sh17)] for ours, sh17 in TARGET_CLASSES.items()
            if class_id(names, sh17) is not None
        }}  # fmt: skip
    in_two_splits = sorted(s for s, c in stems_seen.items() if c > 1)
    no_split = sorted(boxes_by_image.keys() - stems_seen.keys()) if data["splits"] else []

    def split_of(stem: str) -> set[str]:
        return {name for name, stems in data["splits"].items() if stem in stems}

    # Two identical images listed in two different splits: a hidden train/test leak.
    leak_by_duplicate = [
        (a, b) for a, b in data["duplicates"]
        if split_of(a) and split_of(b) and split_of(a) != split_of(b)
    ]  # fmt: skip

    widths = np.array([v["size"][0] for v in data["images"].values() if v["size"]] or [0])
    return {
        "per_class": per_class,
        "persons_per_image": dict(persons_per_image),
        "persons_total": total_persons,
        "persons_with_nothing_annotated": empty_persons,
        "splits": split_counts,
        "images_in_two_splits": in_two_splits,
        "images_in_no_split": no_split,
        "duplicate_pairs_across_splits": leak_by_duplicate,
        "width_px": {
            "min": int(widths.min()),
            "median": int(np.median(widths)),
            "max": int(widths.max()),
        },
    }


# --------------------------------------------------------------------------- outputs


def print_table(rows: list[dict]) -> None:
    if not rows:
        return
    headers = list(dict.fromkeys(k for row in rows for k in row))
    widths = {h: max(len(h), *(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    print("  " + " | ".join(h.ljust(widths[h]) for h in headers))
    print("  " + "-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print("  " + " | ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers))


def print_report(data: dict, stats: dict) -> None:
    n_images = len(data["images"])
    print("\n=== 1. COMPLETENESS ===")
    print(f"  images found                 : {n_images}")
    print(f"  usable images                : {len(data['boxes'])}")
    print(f"  images without label file    : {len(data['missing_label'])}")
    print(f"  empty label files            : {len(data['empty_label'])}")
    print(f"  label files without image    : {len(data['orphan_labels'])}")
    print(f"  images in no split list      : {len(stats['images_in_no_split'])}")
    print(f"  persons with nothing on them : {stats['persons_with_nothing_annotated']}"
          f" / {stats['persons_total']} (maybe not fully annotated)")  # fmt: skip

    print("\n=== 2. QUALITY ===")
    print(f"  unreadable images            : {len(data['corrupt'])}")
    print(f"  exact duplicate images       : {len(data['duplicates'])}")
    print(f"  same image in two splits     : {len(stats['images_in_two_splits'])}")
    print(f"  duplicate pair across splits : {len(stats['duplicate_pairs_across_splits'])}")
    for issue, count in sorted(data["line_issues"].items()):
        print(f"  bad lines: {issue:<19}: {count}")

    print("\n=== 3. CLASSES (our PPE classes + body-part evidence) ===")
    print_table(stats["per_class"])
    print(f"\n  persons per image : {stats['persons_per_image']}")
    print(f"  image width (px)  : {stats['width_px']}")
    if stats["splits"]:
        print("\n=== 4. SPLITS ===")
        print_table([{"split": k, **v} for k, v in stats["splits"].items()])


def save_previews(data: dict, out_dir: Path, count: int, seed: int) -> None:
    """Draw boxes on random images. Faces are blurred: no face is ever stored unblurred."""
    names = data["names"]
    face_id = class_id(names, FACE_CLASS)
    drawn = {class_id(names, n) for n in {**TARGET_CLASSES, **EVIDENCE_CLASSES}.values()}
    stems = sorted(data["boxes"])
    random.Random(seed).shuffle(stems)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem in stems[:count]:
        image = cv2.imread(str(data["images"][stem]["path"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        scale = 1280 / max(image.shape[:2])
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        h, w = image.shape[:2]
        for b in data["boxes"][stem]:
            x1, y1 = int((b.cx - b.w / 2) * w), int((b.cy - b.h / 2) * h)
            x2, y2 = int((b.cx + b.w / 2) * w), int((b.cy + b.h / 2) * h)
            if b.cls == face_id:
                roi = image[max(0, y1):y2, max(0, x1):x2]
                if roi.size:
                    image[max(0, y1):y2, max(0, x1):x2] = cv2.GaussianBlur(roi, (51, 51), 30)
            elif b.cls in drawn:
                color = tuple(int(c) for c in np.random.default_rng(b.cls).integers(60, 255, 3))
                cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
                cv2.putText(image, names[b.cls], (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)  # fmt: skip
        cv2.imwrite(str(out_dir / f"{stem}.jpg"), image)
    print(f"\n{min(count, len(stems))} previews (faces blurred) written to {out_dir}")


def write_clean_copy(data: dict, out_dir: Path) -> None:
    """Cleaned labels + symlinks to the original images + split lists (YOLO layout)."""
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "labels").mkdir(parents=True, exist_ok=True)
    for stem, boxes in data["boxes"].items():
        source = data["images"][stem]["path"].resolve()
        link = out_dir / "images" / source.name
        if not link.exists():
            link.symlink_to(source)
        label_text = "\n".join(b.to_line() for b in boxes) + "\n"
        (out_dir / "labels" / f"{stem}.txt").write_text(label_text)
    images_dir = out_dir.resolve() / "images"  # do NOT resolve the symlinks themselves:
    # YOLO finds labels next to the image path, and must find the cleaned ones.
    for split, stems in data["splits"].items():
        kept = stems & data["boxes"].keys()
        if split == "train":  # an image also used for validation/test leaves the training set
            kept -= set().union(*(s for name, s in data["splits"].items() if name != "train"))
        lines = [str(images_dir / data["images"][s]["path"].name) for s in sorted(kept)]
        (out_dir / f"{split}.txt").write_text("\n".join(lines) + "\n")
    yaml_data = {"path": str(out_dir.resolve()), "names": dict(enumerate(data["names"]))}
    yaml_data.update({s if s != "valid" else "val": f"{s}.txt" for s in data["splits"]})
    (out_dir / "data.yaml").write_text(yaml.safe_dump(yaml_data, sort_keys=False))
    print(f"Cleaned copy ({len(data['boxes'])} images) written to {out_dir}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="dataset folder, e.g. data/sh17")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("data/processed/safety/sh17_report")
    )
    parser.add_argument("--previews", type=int, default=20, help="number of preview images")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fix", type=Path, default=None, help="write a cleaned copy here")
    args = parser.parse_args(argv)

    data = scan(args.root)
    stats = analyse(data)
    print_report(data, stats)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        **stats,
        "counts": {
            k: len(data[k]) for k in ("corrupt", "missing_label", "empty_label", "orphan_labels")
        },
        "line_issues": dict(data["line_issues"]),
        "duplicates": data["duplicates"],
        "examples": {k: data[k][:20] for k in ("corrupt", "missing_label", "empty_label")},
    }
    (args.report_dir / "report.json").write_text(json.dumps(report, indent=2))
    print(f"Full report written to {args.report_dir / 'report.json'}")
    save_previews(data, args.report_dir / "previews", args.previews, args.seed)
    if args.fix:
        write_clean_copy(data, args.fix)


if __name__ == "__main__":
    main()
