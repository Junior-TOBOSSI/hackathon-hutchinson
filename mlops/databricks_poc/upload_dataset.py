"""DBX-00B: create the POC schema and Volume, upload the synthetic dataset, verify it.

    python -m mlops.databricks_poc.upload_dataset

1. schema ``workspace.argos_poc`` and managed Volume ``workspace.argos_poc.images``
   (created only if missing);
2. upload of the 200 PNG files and manifest.json (Files API, from this PC);
3. listing from Databricks, download of sample files and SHA-256 comparison.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time

from databricks.sdk.errors import NotFound, ResourceAlreadyExists
from databricks.sdk.service.catalog import VolumeType

from mlops.databricks_poc.common import (
    CATALOG,
    DATASET_DIR,
    LOCAL_DATASET,
    SCHEMA,
    VOLUME,
    save_result,
    workspace_client,
)


def main() -> int:
    w = workspace_client()
    result: dict = {}
    try:
        w.schemas.create(
            name=SCHEMA, catalog_name=CATALOG, comment="ARGOS DBX-00 POC - synthetic data only"
        )
        result["schema"] = "created"
    except ResourceAlreadyExists:
        result["schema"] = "already existed"
    try:
        w.volumes.read(f"{CATALOG}.{SCHEMA}.{VOLUME}")
        result["volume"] = "already existed"
    except NotFound:
        w.volumes.create(
            catalog_name=CATALOG,
            schema_name=SCHEMA,
            name=VOLUME,
            volume_type=VolumeType.MANAGED,
            comment="ARGOS DBX-00 POC - synthetic images",
        )
        result["volume"] = "created"
    print(f"schema {CATALOG}.{SCHEMA}: {result['schema']}; volume {VOLUME}: {result['volume']}")

    manifest = json.loads((LOCAL_DATASET / "manifest.json").read_text(encoding="utf-8"))
    files = [item["file"] for item in manifest["items"]] + ["manifest.json"]
    start = time.perf_counter()
    for name in files:
        with (LOCAL_DATASET / name).open("rb") as handle:
            w.files.upload(f"{DATASET_DIR}/{name}", handle, overwrite=True)
    result["upload"] = {"files": len(files), "seconds": round(time.perf_counter() - start, 1)}
    print(f"uploaded {len(files)} files in {result['upload']['seconds']} s")

    remote = sorted(
        entry.path
        for split in ("train", "validation", "test")
        for label in ("OK", "NOK")
        for entry in w.files.list_directory_contents(f"{DATASET_DIR}/{split}/{label}")
    )
    result["remote_listing"] = {"png_files": len(remote)}
    print(f"listed from Databricks: {len(remote)} PNG files")

    checks = []
    by_file = {item["file"]: item for item in manifest["items"]}
    for name in (manifest["items"][0]["file"], manifest["items"][-1]["file"]):
        content = w.files.download(f"{DATASET_DIR}/{name}").contents.read()
        digest = hashlib.sha256(content).hexdigest()
        checks.append({"file": name, "sha256_match": digest == by_file[name]["sha256"]})
    remote_manifest = json.load(
        io.BytesIO(w.files.download(f"{DATASET_DIR}/manifest.json").contents.read())
    )
    checks.append(
        {
            "file": "manifest.json",
            "items_match": len(remote_manifest["items"]) == len(manifest["items"]),
        }
    )
    result["download_checks"] = checks
    for check in checks:
        print("download check:", check)

    path = save_result("upload_dataset", result)
    ok = len(remote) == len(manifest["items"]) and all(
        all(v for k, v in c.items() if k != "file") for c in checks
    )
    print(f"{'PASS' if ok else 'FAIL'} - saved to {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
