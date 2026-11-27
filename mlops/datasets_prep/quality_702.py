"""Inventory the Quality 702 ZIP locally without extracting or publishing images.

This is a source audit, not a three-class dataset version. The group's tri_nok.csv and
the human R05 decision are required before classes and final splits can be assigned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from mlops.pipelines.quality_industrial.kit.donnees.preparer_donnees_rafales import (
    SEUIL_RAFALE_S,
)

NAME = re.compile(r"^S6000702_(\d+)\.jpg$", re.IGNORECASE)


def _sha256(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def audit(source: Path) -> dict:
    """Apply the group's 3-second burst boundary to source metadata only."""
    rows = []
    seen_names: set[str] = set()
    with ZipFile(source) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            match = NAME.fullmatch(path.name)
            if (
                len(path.parts) != 3
                or path.parts[0] != "702"
                or path.parts[1] not in {"OK", "NOK"}
                or not match
                or info.filename in seen_names
            ):
                raise ValueError(f"unexpected or duplicate ZIP member: {info.filename}")
            seen_names.add(info.filename)
            with archive.open(info) as stream:
                digest = _sha256(stream)
            rows.append(
                {
                    "source_path": info.filename,
                    "binary_label": path.parts[1],
                    "epoch_ms": int(match.group(1)),
                    "size_bytes": info.file_size,
                    "sha256": digest,
                }
            )
    if not rows:
        raise ValueError("ZIP contains no Quality images")
    rows.sort(key=lambda row: row["epoch_ms"])
    burst = -1
    previous = None
    for row in rows:
        if previous is None or (row["epoch_ms"] - previous) / 1000 > SEUIL_RAFALE_S:
            burst += 1
        row["group"] = f"R{burst:02d}"
        row["split"] = "unassigned"
        previous = row["epoch_ms"]
    hashes = Counter(row["sha256"] for row in rows)
    groups = Counter(row["group"] for row in rows)
    with source.open("rb") as handle:
        source_hash = _sha256(handle)
    mixed = sorted(
        group
        for group in groups
        if len({row["binary_label"] for row in rows if row["group"] == group}) > 1
    )
    return {
        "schema_version": "hovis.quality-source-audit/1",
        "dataset_id": "quality-industrial",
        "source_zip_sha256": source_hash,
        "source_zip": str(source.resolve()),
        "scientific_rule": {
            "module": "preparer_donnees_rafales.py",
            "burst_gap_seconds": SEUIL_RAFALE_S,
        },
        "binary_counts": dict(Counter(row["binary_label"] for row in rows)),
        "burst_counts": dict(groups),
        "exact_duplicate_extra_copies": sum(n - 1 for n in hashes.values()),
        "mixed_binary_label_groups": mixed,
        "r05_exclusion_proposal": {
            "images": groups.get("R05", 0),
            "decision": "pending_human_review",
        },
        "publishable": False,
        "blockers": [
            "tri_nok.csv absent: NOK_SANS/NOK_DOUBLE annotations cannot be assigned",
            "R05 exclusion has not been decided by the group/human reviewer",
            "three-class splits cannot be finalized without these decisions",
            "industrial-image privacy and transfer review must be recorded before upload",
        ],
        "items": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, required=True)
    home = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))
    parser.add_argument("--output", type=Path, default=home / "prep/quality-702/source-audit.json")
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[2]
    if args.output.resolve().is_relative_to(checkout):
        parser.error("audit output must stay outside Git")
    result = audit(args.zip)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: result[k] for k in ("binary_counts", "burst_counts", "blockers")}, indent=2)
    )
    print(f"audit: {args.output}")


if __name__ == "__main__":
    main()
