"""Publish a locally prepared INDUSTRIAL dataset version to the Unity Catalog Volume (SCI-02).

The standard Datasets import requires a "synthetic" attestation and refuses industrial images
(on purpose). This tool is the distinct, explicit path for prepared industrial versions
(e.g. ``quality-industrial-binary/binary-pli0``). It reuses the DatasetStore primitives, so the
published version has EXACTLY the catalogue guarantees:

- immutable version folder, one publication at a time (lock), ``overwrite=False`` everywhere;
- every file re-read and its SHA-256 verified after upload; manifest written LAST;
- an interrupted publication is reported by the catalogue, never shown as a version.

DEFAULT = DRY RUN: local checks (presence, SHA-256, counts, no burst leak) + remote READ-ONLY
checks (family / version existence). The transfer happens only with ALL of:
``--execute``, ``HOVIS_INDUSTRIAL_TRANSFER=1`` and ``--confirm <dataset_id>/<version>``.
No image content is ever printed or logged; no training is ever triggered.

    python -m mlops.datasets_prep.publish_industrial --prepared <dir with the draft manifest>
    $env:HOVIS_INDUSTRIAL_TRANSFER = '1'
    python -m mlops.datasets_prep.publish_industrial --prepared <dir> --execute \
        --confirm quality-industrial-binary/binary-pli0 --family-name "Qualité 702 binaire"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DRAFT = "manifest.catalog-draft.json"
SPLIT_DIRS = {"train": "train", "validation": "val", "test": "test"}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_local(prepared: Path) -> tuple[dict[str, Any], list[str]]:
    """Local checks only. Returns (manifest, errors)."""
    manifest = json.loads((prepared / DRAFT).read_text(encoding="utf-8"))
    errors: list[str] = []
    items = manifest.get("items", [])
    if manifest.get("synthetic") is not False:
        errors.append("manifest must declare synthetic=false for an industrial version")
    if not items:
        errors.append("manifest has no item")
    groups: dict[str, set[str]] = {}
    for it in items:
        path = prepared.joinpath(*it["file"].split("/"))
        if not path.is_file():
            errors.append(f"missing file {it['file']}")
        elif _sha(path) != it["sha256"]:
            errors.append(f"SHA-256 mismatch {it['file']}")
        if it.get("label") not in manifest.get("classes", []):
            errors.append(f"unknown label in {it['file']}")
        groups.setdefault(str(it.get("group")), set()).add(it["split"])
    leaks = [g for g, s in groups.items() if len(s) > 1]
    if leaks:
        errors.append(f"{len(leaks)} burst(s) in several splits")
    counts = Counter((it["split"], it["label"]) for it in items)
    declared = {
        (s, lab): n for s, labs in manifest.get("counts", {}).items() for lab, n in labs.items()
    }
    if declared and dict(counts) != {k: v for k, v in declared.items() if v}:
        errors.append("declared counts differ from the items")
    if len(set(it["sha256"] for it in items)) != len(items):
        errors.append("duplicate images (same SHA-256)")
    return manifest, errors


def published_manifest(draft: dict[str, Any]) -> dict[str, Any]:
    """Catalogue manifest: the prepared one + publication metadata (items unchanged)."""
    out = dict(draft)
    out["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    out["created_by"] = "publish_industrial (SCI-02)"
    out["provenance"] = {
        **draft.get("provenance", {}),
        "publication": "industrial explicit path",
        "source_sha256": draft.get("source_sha256"),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prepared", required=True, type=Path)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--family-name", default=None)
    args = ap.parse_args(argv)

    manifest, errors = check_local(args.prepared)
    ds, version = manifest.get("dataset_id"), manifest.get("dataset_version")
    print(
        f"dataset {ds} version {version}: {len(manifest.get('items', []))} images, "
        f"classes {manifest.get('classes')}, synthetic={manifest.get('synthetic')}"
    )
    if errors:
        print("LOCAL CHECKS FAILED:\n  " + "\n  ".join(errors[:20]))
        return 2
    print("local checks: OK (files, SHA-256, labels, counts, no burst leak, no duplicate)")

    from mlops.api.routes import default_connector
    from mlops.databricks.datasets import check_version_name, dataset_store

    check_version_name(ds)
    check_version_name(version)
    store = dataset_store(default_connector())
    root = f"{store.catalog_root}/{ds}"
    family_exists = store._exists(f"{root}/family.json")
    version_exists = store._exists(f"{root}/{version}/manifest.json")
    print(
        f"target {root}/{version} | family exists: {family_exists} | "
        f"version exists: {version_exists}"
    )
    if version_exists:
        print("version already published: nothing to do (versions are immutable)")
        return 0

    if not args.execute:
        print(
            "DRY RUN: nothing transferred. Transfer needs --execute, HOVIS_INDUSTRIAL_TRANSFER=1 "
            f"and --confirm {ds}/{version}"
        )
        return 0
    if os.environ.get("HOVIS_INDUSTRIAL_TRANSFER") != "1" or args.confirm != f"{ds}/{version}":
        print(
            "REFUSED: industrial transfer needs HOVIS_INDUSTRIAL_TRANSFER=1 and "
            f"--confirm {ds}/{version}"
        )
        return 3

    if not family_exists:
        store.create_family(
            ds,
            args.family_name or ds,
            manifest["use_case"],
            manifest["classes"],
            synthetic=False,
            description="industrial images (explicit SCI-02 publication)",
        )
    lock = f"{root}/_locks/{version}.lock"
    store._acquire_lock(lock, uuid.uuid4().hex, f"industrial:{version}")
    try:
        _transfer(store, root, version, manifest, args.prepared)
    finally:  # same as the catalogue publication: the lock is always removed
        try:
            store.c._call(lambda: store.w.files.delete(lock), "lock")
        except Exception:  # noqa: BLE001 - a stale lock of the same publication can be resumed
            pass
    return 0


def _transfer(store, root: str, version: str, manifest: dict[str, Any], prepared: Path) -> None:
    from mlops.databricks.datasets import manifest_bytes, sha256

    ds = manifest["dataset_id"]
    items = manifest["items"]
    for n, it in enumerate(items, 1):
        dst = f"{root}/{version}/{it['file']}"
        local = prepared.joinpath(*it["file"].split("/"))
        if store._exists(dst):  # resume: only an identical file is accepted
            if sha256(store._download(dst)) != it["sha256"]:
                raise SystemExit(f"{it['file']} already exists with other content")
        else:
            store._upload(dst, local.read_bytes())
        store._verify(dst, it["sha256"])
        if n % 100 == 0 or n == len(items):
            print(f"  {n}/{len(items)} files uploaded and verified")
    raw = manifest_bytes(published_manifest(manifest))
    store._upload(f"{root}/{version}/manifest.json", raw)  # LAST write, never overwrites
    if sha256(store._download(f"{root}/{version}/manifest.json")) != sha256(raw):
        raise SystemExit("manifest read back differs from the written one")
    store._refresh_family_summary(f"family:{ds}")
    print(
        f"published {ds}/{version} (manifest SHA-256 {sha256(raw)[:16]}…). "
        "No training was triggered."
    )


if __name__ == "__main__":
    sys.exit(main())
