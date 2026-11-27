"""Materialise a published dataset version in the layout expected by a group's pipeline.

Standard library only: it runs inside the Databricks job. The published version is never
modified: files are COPIED to an isolated working folder after their SHA-256 is verified.

Quality layout::

    <dst>/train|val|test/<CLASS>/<file>.jpg   +   <dst>/repartition.csv
    repartition.csv columns (group's format): fichier, classe, type, rafale, pli, split
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path, PurePosixPath


class MaterializationError(Exception):
    pass


def check_groups(items: list[dict], group_field: str | None, required: bool) -> None:
    if not group_field:
        return
    splits_of: dict[str, set[str]] = {}
    for item in items:
        group = item.get(group_field)
        if not group:
            if required:
                raise MaterializationError(f"{item['file']}: no {group_field}")
            continue
        splits_of.setdefault(group, set()).add(item["split"])
    leaks = sorted(g for g, s in splits_of.items() if len(s) > 1)
    if leaks:
        raise MaterializationError(f"groups across splits (leakage): {leaks}")


def materialize(
    manifest: dict,
    src_dir: Path,
    dst_dir: Path,
    split_names: dict[str, str],
    extensions: list[str],
    group_field: str | None = None,
    group_required: bool = False,
) -> dict[str, dict[str, int]]:
    """Copy + verify every item; returns {split: {class: count}} in the pipeline's names."""
    items = manifest["items"]
    check_groups(items, group_field, group_required)
    if dst_dir.exists() and any(dst_dir.iterdir()):
        raise MaterializationError(f"{dst_dir} is not empty (one working folder per run)")
    counts: dict[str, dict[str, int]] = {}
    names: set[tuple[str, str, str]] = set()
    rows = []
    for item in items:
        name = PurePosixPath(item["file"]).name
        if PurePosixPath(name).suffix.lower() not in extensions:
            raise MaterializationError(f"{item['file']}: extension not accepted by the pipeline")
        split = split_names.get(item["split"], item["split"])
        key = (split, item["label"], name)
        if key in names:
            raise MaterializationError(f"two items would land on {'/'.join(key)}")
        names.add(key)
        data = (src_dir / item["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise MaterializationError(f"{item['file']}: SHA-256 mismatch")
        target = dst_dir / split / item["label"] / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        counts.setdefault(split, {}).setdefault(item["label"], 0)
        counts[split][item["label"]] += 1
        rows.append(
            {
                "fichier": name,
                "classe": "OK" if item["label"] == "OK" else "NOK",
                "type": item["label"],
                "rafale": item.get(group_field or "", "") or "",
                "pli": item.get("fold", ""),
                "split": split,
            }
        )
    with open(dst_dir / "repartition.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["fichier", "classe", "type", "rafale", "pli", "split"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return counts


def clean(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
