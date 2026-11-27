"""DBX-04-FINAL: local preparation of the `presse-5s` dataset family (Workstation / 5S).

    python -m mlops.datasets_prep.presse_5s prepare --zip <presse_5S_20.zip>
    python -m mlops.datasets_prep.presse_5s import --zip <...> --api http://127.0.0.1:8020/api \
        --i-have-explicit-authorization      # ONLY after the user's explicit authorization

`prepare` (local only, nothing is sent anywhere):
- checks the archive (CRC), reads labels.csv (the real 4 classes; folders are only good/anomaly);
- drops `reference.png`, byte-identical to good/good_001.png (not an extra sample);
- keeps every image byte-for-byte (no conversion, no anonymisation, no edit);
- groups related images by SOURCE (labels.csv `source`): the 14 crops of ONE generated sheet
  are near-duplicates of each other, so they must stay in the same split;
- proposes a source-grouped split and writes, under <ARGOS_MLOPS_HOME>/prep/presse-5s/v1/:
  images/<split>/<label>/<file>, plan.json (sha256, label, split, source, notes), REVIEW.md.

`import` replays plan.json through the HOVIS dataset API (family creation, first draft,
bounded imports per label/split, publication of `v1`): no parallel storage, same guarantees
(SHA-256, immutable version, manifest written last). It refuses to run without the flag.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

FAMILY = {
    "dataset_id": "presse-5s",
    "name": "Presse — Workstation / 5S",
    "use_case": "workstation",
    "classes": ["good", "disorder", "zone_object", "zone_person"],
    "synthetic": True,
    "description": "20 synthetic images (README of the delivery): 6 from a validated pilot lot, "
    "14 crops of one generated sheet. Source-grouped split. Prototype only.",
}
VERSION = "v1"
DUPLICATE_OF_REFERENCE = "reference.png"
# Source groups (labels.csv `source`) -> split. The sheet crops are near-duplicates: one group.
SPLIT_BY_SOURCE = {"planche generee recadree": "train", "lot pilote valide": "test"}
HOME = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))
OUT = HOME / "prep" / "presse-5s" / VERSION


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_plan(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        if z.testzip() is not None:
            raise SystemExit("archive integrity check failed")
        labels = list(csv.DictReader(io.StringIO(z.read("labels.csv").decode("utf-8"))))
        blobs = {n: z.read(n) for n in z.namelist() if n.lower().endswith(".png")}
    reference = sha256(blobs.pop(DUPLICATE_OF_REFERENCE))
    items, problems = [], []
    for row in labels:
        data = blobs.pop(row["filename"], None)
        if data is None:
            problems.append(f"missing image {row['filename']}")
            continue
        if row["label"] not in FAMILY["classes"]:
            problems.append(f"unknown label {row['label']}")
        split = SPLIT_BY_SOURCE.get(row["source"])
        if split is None:
            problems.append(f"unknown source {row['source']}")
        items.append(
            {
                "file": row["filename"],
                "name": Path(row["filename"]).name,
                "label": row["label"],
                "split": split,
                "source": row["source"],
                "notes": row["notes"],
                "sha256": sha256(data),
                "size": len(data),
                "possible_person": row["label"] == "zone_person" or "operateur" in row["notes"],
            }
        )
    if blobs:
        problems.append(f"images without label: {sorted(blobs)}")
    if len({i["sha256"] for i in items}) != len(items):
        problems.append("duplicate images among labelled samples")
    groups = {}
    for i in items:
        groups.setdefault(i["source"], set()).add(i["split"])
    leaks = [g for g, s in groups.items() if len(s) > 1]
    if leaks:
        problems.append(f"source groups across splits: {leaks}")
    counts = {}
    for i in items:
        counts.setdefault(i["split"], {}).setdefault(i["label"], 0)
        counts[i["split"]][i["label"]] += 1
    return {
        "family": FAMILY,
        "version": VERSION,
        "zip_sha256": sha256(zip_path.read_bytes()),
        "excluded": [
            {
                "file": DUPLICATE_OF_REFERENCE,
                "reason": "byte-identical to good/good_001.png",
                "sha256": reference,
            }
        ],
        "split_strategy": "by_source (labels.csv `source`): related crops of the generated sheet "
        "stay together; the independent pilot lot is the test set; no validation split (20 images)",
        "counts": counts,
        "items": items,
        "problems": problems,
    }


def prepare(zip_path: Path) -> int:
    plan = build_plan(zip_path)
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for i in plan["items"]:
            dst = OUT / "images" / i["split"] / i["label"] / i["name"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(i["file"]))  # unchanged bytes
    (OUT / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    review = [
        "# presse-5s v1 — human review before any transfer",
        "",
        "Open the images LOCALLY (this folder). HOVIS never displays them before this review.",
        "",
        "Check on EVERY image: no real face or identifiable person, no confidential information "
        "(logos, documents, screens, plates), synthetic provenance plausible.",
        "",
        "Priority (persons expected from labels.csv):",
        "",
    ]
    review += [
        f"- [ ] images/{i['split']}/{i['label']}/{i['name']} — {i['notes']}"
        for i in plan["items"]
        if i["possible_person"]
    ]
    review += ["", "Others:", ""]
    review += [
        f"- [ ] images/{i['split']}/{i['label']}/{i['name']} — {i['notes']}"
        for i in plan["items"]
        if not i["possible_person"]
    ]
    (OUT / "REVIEW.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    print(f"prepared {len(plan['items'])} images in {OUT}")
    print("counts:", json.dumps(plan["counts"]))
    print("problems:", plan["problems"] or "none")
    return 1 if plan["problems"] else 0


# ------------------------------------------------------------ import (authorized only)


def _call(api: str, method: str, path: str, body=None, form=None):
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    if form is not None:
        boundary = uuid.uuid4().hex
        parts = []
        crlf = "\r\n"
        for key, value in form["fields"].items():
            head = f'Content-Disposition: form-data; name="{key}"'
            parts.append(f"--{boundary}{crlf}{head}{crlf}{crlf}{value}{crlf}".encode())
        for name, blob in form["files"]:
            head = f'Content-Disposition: form-data; name="files"; filename="{name}"'
            mime = "Content-Type: image/png"
            parts.append(
                f"--{boundary}{crlf}{head}{crlf}{mime}{crlf}{crlf}".encode() + blob + b"\r\n"
            )
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(api + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def import_plan(zip_path: Path, api: str) -> int:
    plan = build_plan(zip_path)
    if plan["problems"]:
        raise SystemExit(f"plan has problems: {plan['problems']}")
    fam = FAMILY["dataset_id"]
    existing = {f["dataset_id"] for f in _call(api, "GET", "/mlops/datasets")}
    if fam not in existing:
        _call(
            api,
            "POST",
            "/mlops/datasets",
            {
                k: FAMILY[k]
                for k in ("dataset_id", "name", "use_case", "classes", "synthetic", "description")
            },
        )
    draft = _call(api, "POST", f"/mlops/datasets/{fam}/drafts", {"parent_version": None})
    did = draft["draft_id"]
    with zipfile.ZipFile(zip_path) as z:
        for label, split in sorted({(i["label"], i["split"]) for i in plan["items"]}):
            batch = [
                (i["name"], z.read(i["file"]))
                for i in plan["items"]
                if i["label"] == label and i["split"] == split
            ]
            res = _call(
                api,
                "POST",
                f"/mlops/datasets/{fam}/drafts/{did}/import",
                form={
                    "fields": {"label": label, "split": split, "synthetic_attested": "true"},
                    "files": batch,
                },
            )
            refused = [r for r in res if not r["accepted"]]
            accepted = len(res) - len(refused)
            print(f"import {label}/{split}: {accepted} accepted, {len(refused)} refused")
            if refused:
                raise SystemExit(f"refused: {refused}")
    job = _call(api, "POST", f"/mlops/datasets/{fam}/drafts/{did}/publish", {"version": VERSION})
    while job["state"] == "running":
        time.sleep(1)
        job = _call(api, "GET", f"/mlops/dataset-jobs/{job['job_id']}")
    print("publication:", job["state"], job.get("manifest_sha256") or job.get("error"))
    return 0 if job["state"] == "succeeded" else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["prepare", "import"])
    p.add_argument("--zip", required=True, type=Path)
    p.add_argument("--api", default="http://127.0.0.1:8020/api")
    p.add_argument("--i-have-explicit-authorization", action="store_true")
    a = p.parse_args()
    if a.command == "prepare":
        return prepare(a.zip)
    if not a.i_have_explicit_authorization:
        raise SystemExit("import refused: explicit user authorization required (see REVIEW.md)")
    return import_plan(a.zip, a.api)


if __name__ == "__main__":
    sys.exit(main())
