"""Stage the four original Workstation group datasets without publishing them.

Usage: python -m mlops.datasets_prep.workstation_group --source-root <raw/workstation>
    --output-root <private staging folder>

Missing sections are reported and not replaced with generated samples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path, PurePosixPath

import yaml

KIT = Path(__file__).resolve().parents[1] / "pipelines/workstation/kit/usecases/workstation"
SECTIONS = {
    "press_cell": "poste-5s-11",
    "machine_cell": "poste-bleu-5s-11",
    "machine_cell_variant": "poste-variante-5s-11",
    "electrical_bench": "poste-electrique-5s-11",
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def stage(section: str, source_root: Path, output_root: Path) -> Path:
    if output_root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("Workstation images must be staged outside the Git repository")
    config = yaml.safe_load((KIT / "stations" / f"{section}.yaml").read_text(encoding="utf-8"))
    dataset_name = PurePosixPath(config["dataset"]).name
    source = source_root / dataset_name
    labels_file = source / "labels.csv"
    if not labels_file.is_file():
        raise FileNotFoundError(f"{section}: {labels_file}")
    with labels_file.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    columns = config["labels"]
    items = []
    for row in rows:
        filename = (row.get(columns["file"]) or "").strip()
        original_label = (row.get(columns["label"]) or "").strip()
        if not filename or Path(filename).name != filename:
            raise ValueError(f"{section}: unsafe or absent image filename")
        if original_label == "reference":
            continue
        if original_label not in {"good", "anomaly"}:
            raise ValueError(f"{section}: unexpected original label {original_label!r}")
        image = source / filename
        if not image.is_file() or image.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise FileNotFoundError(image)
        kind = (row.get(columns["type"]) or "").strip()
        items.append(
            {
                "file": f"raw/workstation/{dataset_name}/{filename}",
                "label": original_label,
                "split": "train" if original_label == "good" else "test",
                "sha256": digest(image),
                "anomaly_type": kind if original_label == "anomaly" else None,
                "origin": "workstation-group-original",
            }
        )
    reference_files = {PurePosixPath(view["reference_image"]).name for view in config["views"]}
    assets = []
    for name in sorted(reference_files | {"labels.csv"}):
        file = source / name
        if not file.is_file():
            raise FileNotFoundError(file)
        assets.append({"file": f"raw/workstation/{dataset_name}/{name}", "sha256": digest(file)})
    counts = Counter(item["label"] for item in items)
    if counts != {"good": 5, "anomaly": 5}:
        raise ValueError(
            f"{section}: expected group's five good and five anomaly photos, got {counts}"
        )
    family = SECTIONS[section]
    version_root = output_root / family / "group-v1"
    if version_root.exists():
        raise FileExistsError(version_root)
    target = version_root / "raw/workstation" / dataset_name
    target.mkdir(parents=True)
    for entry in [*items, *assets]:
        name = PurePosixPath(entry["file"]).name
        shutil.copy2(source / name, target / name)
    manifest = {
        "schema_version": 2,
        "dataset_id": family,
        "dataset_version": "group-v1",
        "station": section,
        "use_case": "workstation",
        "annotation_format": "classification",
        "classes": ["good", "anomaly"],
        "synthetic": True,
        "description": (
            "Original group dataset: real reference and good photos, group-made anomalies."
        ),
        "split_strategy": "group-cross-validation-inside-evaluator",
        "provenance": {
            "source": "workstation-group",
            "section": section,
            "source_dataset": dataset_name,
        },
        "counts": {
            split: {
                label: sum(item["split"] == split and item["label"] == label for item in items)
                for label in ("good", "anomaly")
            }
            for split in ("train", "validation", "test")
        },
        "split_fingerprints": {
            split: hashlib.sha256(
                "\n".join(
                    sorted(
                        f"{item['sha256']}:{item['label']}"
                        for item in items
                        if item["split"] == split
                    )
                ).encode()
            ).hexdigest()
            for split in ("train", "validation", "test")
        },
        "items": sorted(items, key=lambda item: item["file"]),
        "assets": assets,
    }
    (version_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return version_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    for section in SECTIONS:
        try:
            path = stage(section, args.source_root, args.output_root)
            print(f"{section}: staged {path}")
        except FileNotFoundError as exc:
            print(f"{section}: awaiting original dataset ({exc})")


if __name__ == "__main__":
    main()
