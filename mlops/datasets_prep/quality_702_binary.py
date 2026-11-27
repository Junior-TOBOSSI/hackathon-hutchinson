"""Stage the original 839-image Quality binary dataset with the group's five-fold splitter.

All output stays in a private local folder; this command never contacts Databricks.
Usage: python -m mlops.datasets_prep.quality_702_binary --archive Dataset.zip
    --output-root <private-folder>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "pipelines/quality_industrial/kit/donnees/preparer_donnees_rafales.py"
)
SOURCE_SHA256 = "eb6922a6f7018339608fca98ecd83dcf1c240eabbc3901f819ccd19fc3b4841b"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def stage(archive: Path, root: Path) -> dict:
    if root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("industrial images must be staged outside the Git repository")
    if digest(archive) != SOURCE_SHA256:
        raise ValueError("Quality archive does not match the audited original")
    raw = root / "702"
    original: dict[str, tuple[str, str]] = {}
    with ZipFile(archive) as zipped:
        members = [m for m in zipped.infolist() if not m.is_dir()]
        counts = Counter(m.filename.split("/")[1] for m in members)
        if len(members) != 839 or counts != {"OK": 471, "NOK": 368}:
            raise ValueError(f"unexpected original binary annotations: {counts}")
        for member in members:
            parts = member.filename.split("/")
            if (
                len(parts) != 3
                or parts[0] != "702"
                or parts[1] not in {"OK", "NOK"}
                or not parts[2].endswith(".jpg")
            ):
                raise ValueError(f"unsafe or unexpected archive member: {member.filename}")
            name = parts[2]
            if name in original:
                raise ValueError(f"duplicate image name: {name}")
            target = raw / parts[1] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            expected = hashlib.sha256(zipped.read(member)).hexdigest()
            if not target.exists():
                with zipped.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            if digest(target) != expected:
                raise ValueError(f"local copy differs from the archived original: {name}")
            original[name] = (parts[1], expected)
    folds = []
    assignments = []
    for fold in range(5):
        folder = root / f"dataset_702_binary_pli{fold}"
        if not (folder / "repartition.csv").is_file():
            if folder.exists() and any(folder.iterdir()):
                raise ValueError(f"incomplete existing fold: {folder}")
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--donnees",
                    str(raw),
                    "--sortie",
                    str(folder),
                    "--pli",
                    str(fold),
                ],
                check=True,
            )
        with (folder / "repartition.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 839 or len({r["fichier"] for r in rows}) != 839:
            raise ValueError(f"fold {fold}: missing or repeated image")
        items, burst_splits = [], defaultdict(set)
        split_counts = Counter()
        for row in rows:
            name, label, split, burst = (row[k] for k in ("fichier", "classe", "split", "rafale"))
            if (
                name not in original
                or original[name][0] != label
                or split not in {"train", "val", "test"}
            ):
                raise ValueError(f"fold {fold}: original annotation or split changed")
            file = folder / split / label / name
            if not file.is_file() or digest(file) != original[name][1]:
                raise ValueError(f"fold {fold}: changed image {file}")
            burst_splits[burst].add(split)
            split_counts[split, label] += 1
            items.append(
                {
                    "file": file.relative_to(folder).as_posix(),
                    "label": label,
                    "split": "validation" if split == "val" else split,
                    "sha256": original[name][1],
                    "group": burst,
                    "fold": int(row["pli"]),
                    "origin": "original-industrial-binary-annotation",
                }
            )
        if len(burst_splits) != 29 or any(len(splits) != 1 for splits in burst_splits.values()):
            raise ValueError(f"fold {fold}: burst leakage")
        if any(
            split_counts[split, label] == 0
            for split in ("train", "val", "test")
            for label in ("OK", "NOK")
        ):
            raise ValueError(f"fold {fold}: empty class in a split")
        r05 = [r for r in rows if r["rafale"] == "R05"]
        if len(r05) != 51:
            raise ValueError(f"fold {fold}: R05 exclusion is not authorized")
        assignments.append({burst: next(iter(splits)) for burst, splits in burst_splits.items()})
        manifest = {
            "schema_version": 2,
            "dataset_id": "quality-industrial-binary",
            "dataset_version": f"binary-pli{fold}",
            "use_case": "quality",
            "annotation_format": "classification",
            "classes": ["OK", "NOK"],
            "synthetic": False,
            "split_strategy": "grouped-burst-five-fold",
            "source_sha256": SOURCE_SHA256,
            "splitter_sha256": digest(SCRIPT),
            "r05_included": True,
            "counts": {
                split: {
                    label: sum(item["split"] == split and item["label"] == label for item in items)
                    for label in ("OK", "NOK")
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
        }
        (folder / "manifest.catalog-draft.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        folds.append(
            {
                "fold": fold,
                "counts": {f"{s}/{c}": n for (s, c), n in sorted(split_counts.items())},
                "repartition_sha256": digest(folder / "repartition.csv"),
            }
        )
    for burst in assignments[0]:
        if (
            sum(a[burst] == "test" for a in assignments) != 1
            or sum(a[burst] == "val" for a in assignments) != 1
        ):
            raise ValueError(f"burst {burst} was not evaluated exactly once")
    result = {
        "dataset_id": "quality-industrial-binary",
        "source_sha256": SOURCE_SHA256,
        "images": 839,
        "classes": {"OK": 471, "NOK": 368},
        "bursts": 29,
        "r05_images": 51,
        "folds": folds,
        "publication": "local-draft-only",
    }
    (root / "binary-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.archive, args.output_root)
    print(json.dumps({k: v for k, v in result.items() if k != "folds"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
