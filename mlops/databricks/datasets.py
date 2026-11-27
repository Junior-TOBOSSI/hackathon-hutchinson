"""DBX-04: dataset versions stored in a Unity Catalog Volume (Files API only, no compute).

Source of truth: ``<dataset_root>/<version>/manifest.json``. A version is a self-contained,
immutable folder (its images + its manifest). The Delta tables ``annotations`` /
``dataset_versions`` are mirrors written by the training job; they are never read here
(reading them needs a SQL warehouse), only their Unity Catalog metadata.

Layout::

    <root>/synthetic-v1/manifest.json + train|validation|test/<label>/*.png   (DBX-00)
    <root>/<new-version>/...                                                  (published here)
    <root>/_drafts/<draft_id>/draft.json + files/<sha256>.<ext>               (drafts)
    <root>/_locks/<version>.lock                                              (publication lock)

Guarantees (enforced by THIS API — Databricks itself does not make a folder read-only):

- a published folder is never rewritten: every write uses ``overwrite=False`` and an
  existing destination file is accepted only if its SHA-256 is the expected one (resume);
- a version is valid only when its ``manifest.json`` exists; the manifest is written LAST,
  after every file has been re-downloaded and its SHA-256 verified. A folder without a
  manifest is reported as an interrupted publication, never as a version;
- one publication per version at a time (lock file + re-read of a unique token);
- inherited items keep their split; an image of the parent (any split, excluded or not)
  cannot be imported again (SHA-256 duplicate), so a test image cannot move to train;
- every annotation change is recorded (``label_history``, ``previous_label``, excluded
  items list); any change touching validation/test is flagged as a change of the
  evaluation reference; per-split fingerprints tell whether two evaluations are comparable;
- a publication never triggers a training job.
"""

from __future__ import annotations

import contextvars
import hashlib
import io
import json
import logging
import re
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from mlops.databricks.connector import (
    ConflictError,
    DatabricksConnectorError,
    ForbiddenOperationError,
    ResourceNotFoundError,
)
from visionhub.integration.mlops import DatasetRef

if TYPE_CHECKING:
    from mlops.databricks.connector import DatabricksConnector
    from mlops.databricks.settings import ManagedModel

SPLITS = ("train", "validation", "test")
EVALUATION_SPLITS = {"validation", "test"}
VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
RESERVED = {"code", "runs", "_drafts", "_locks", "_families"}
DRAFT_ID_RE = re.compile(r"^[0-9a-f]{12}$")
GROUP_RE = re.compile(r"^[A-Za-z0-9_.\- ]{1,80}$")
FILE_RE = re.compile(r"^[A-Za-z0-9_.\-/]{1,200}$")

MAX_IMPORT_FILES = 50
MAX_IMPORT_FILE_BYTES = 2 * 1024 * 1024
MAX_IMPORT_REQUEST_BYTES = 25 * 1024 * 1024
MAX_IMAGE_SIDE = 4096
MAX_SERVED_IMAGE_BYTES = 5 * 1024 * 1024
LOCK_STALE_AFTER = timedelta(minutes=15)
PAGE_MAX = 48


class InvalidDatasetRequest(DatabricksConnectorError):
    status_code = 400


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def safe_relative_file(file: str) -> str:
    """Normalised relative path inside a version folder, or InvalidDatasetRequest."""
    if not FILE_RE.match(file) or file.startswith("/") or "\\" in file:
        raise InvalidDatasetRequest("invalid file path")
    parts = file.split("/")  # raw segments: no silent normalisation
    if any(p in ("..", ".", "") for p in parts) or parts[0] in RESERVED:
        raise InvalidDatasetRequest("invalid file path")
    return "/".join(parts)


def check_version_name(version: str) -> str:
    if not VERSION_RE.match(version) or version in RESERVED:
        raise InvalidDatasetRequest(
            "invalid version name (lowercase letters, digits and dashes, 2 to 41 characters)"
        )
    return version


# --------------------------------------------------------------------------- manifest logic


def split_fingerprints(items: list[dict]) -> dict[str, str]:
    """SHA-256 of the sorted (image sha256, label) pairs of each split: two evaluations are
    comparable on a split only when this fingerprint is identical."""
    out = {}
    for split in SPLITS:
        pairs = sorted(f"{i['sha256']}:{i['label']}" for i in items if i["split"] == split)
        out[split] = sha256("\n".join(pairs).encode())
    return out


def counts(items: list[dict], classes: list[str]) -> dict[str, dict[str, int]]:
    labels = list(dict.fromkeys([*classes, *(i["label"] for i in items)]))
    return {
        s: {lab: sum(1 for i in items if i["split"] == s and i["label"] == lab) for lab in labels}
        for s in SPLITS
    }


def annotation_format(manifest: dict) -> str:
    return manifest.get("annotation_format") or (
        "classification" if all("label" in i for i in manifest.get("items", [])) else "unknown"
    )


def build_manifest(
    parent: dict,
    parent_sha: str,
    draft: dict,
    version: str,
    created_at: str,
    use_case: str,
) -> tuple[dict, list[dict]]:
    """New manifest + copy plan from a parent manifest and a draft. Pure and deterministic
    (same inputs -> same bytes, except ``created_at``).

    Copy plan entries: ``{"source": "parent"|"draft", "src": <relative path>, "dst": <relative
    path in the new version>, "sha256": <expected>}``.
    """
    parent_version = parent["dataset_version"]
    fmt = annotation_format(parent)
    classes = list(parent.get("classes") or [])
    changes: dict[str, dict] = draft.get("changes", {})
    items, plan, excluded, evaluation_changes = [], [], [], []
    stats = {"validated": 0, "corrected": 0, "excluded": 0, "imported": 0}
    by_file = {i["file"]: i for i in parent["items"]}
    unknown = sorted(set(changes) - set(by_file))
    if unknown:
        raise InvalidDatasetRequest(f"draft refers to files absent from {parent_version}")

    for item in parent["items"]:
        change = changes.get(item["file"], {})
        if change.get("action") == "exclude":
            excluded.append({k: item[k] for k in ("file", "sha256", "label", "split")})
            stats["excluded"] += 1
            if item["split"] in EVALUATION_SPLITS:
                evaluation_changes.append(
                    {"file": item["file"], "split": item["split"], "change": "excluded"}
                )
            continue
        new = {k: v for k, v in item.items() if k not in ("review", "note")}
        history = list(
            item.get("label_history") or [{"version": parent_version, "label": item["label"]}]
        )
        new["origin"] = item.get("origin") or {"version": parent_version, "file": item["file"]}
        action = change.get("action")
        if action == "relabel":
            if fmt != "classification":
                raise InvalidDatasetRequest("label correction is only supported for classification")
            new["previous_label"] = item["label"]
            new["label"] = change["label"]
            new["review"] = "corrected"
            stats["corrected"] += 1
            if item["split"] in EVALUATION_SPLITS:
                evaluation_changes.append(
                    {"file": item["file"], "split": item["split"], "change": "corrected"}
                )
        elif action == "validate":
            new["review"] = "validated"
            stats["validated"] += 1
        if action in ("relabel", "validate"):
            entry = {"version": version, "label": new["label"], "review": new["review"]}
            if change.get("note"):
                entry["note"] = str(change["note"])[:300]
            history.append(entry)
        new["label_history"] = history
        # Folder follows the label (the training job only reads `file` and `label`).
        name = PurePosixPath(item["file"]).name
        new["file"] = (
            f"{item['split']}/{new['label']}/{name}" if fmt == "classification" else item["file"]
        )
        items.append(new)
        plan.append(
            {"source": "parent", "src": item["file"], "dst": new["file"], "sha256": item["sha256"]}
        )

    for imp in draft.get("imports", []):
        dst = f"{imp['split']}/{imp['label']}/imp_{imp['sha256'][:16]}{imp['ext']}"
        items.append(
            {
                "file": dst,
                "label": imp["label"],
                "split": imp["split"],
                "sha256": imp["sha256"],
                "brightness": None,
                "noise": None,
                "defect": None,
                "width": imp["width"],
                "height": imp["height"],
                "format": imp["format"],
                "origin": {"import": imp["original_name"], "draft_id": draft["draft_id"]},
                **({"group": imp["group"]} if imp.get("group") else {}),
                "review": "imported",
                "label_history": [
                    {"version": version, "label": imp["label"], "review": "imported"}
                ],
            }
        )
        plan.append({"source": "draft", "src": imp["stored"], "dst": dst, "sha256": imp["sha256"]})
        stats["imported"] += 1
        if imp["split"] in EVALUATION_SPLITS:
            evaluation_changes.append({"file": dst, "split": imp["split"], "change": "imported"})

    shas = [i["sha256"] for i in items]
    if len(shas) != len(set(shas)):
        raise InvalidDatasetRequest("duplicate image (same SHA-256) in the new version")
    files = [i["file"] for i in items]
    if len(files) != len(set(files)):
        raise InvalidDatasetRequest("two items would have the same file path")
    items.sort(key=lambda i: i["file"])
    plan.sort(key=lambda p: p["dst"])

    inherited = {k: v for k, v in parent.items() if k not in ("items", "counts", "split_ratios")}
    manifest = {
        **inherited,
        "schema_version": 2,
        "dataset_version": version,
        "parent_version": parent_version,
        "parent_manifest_sha256": parent_sha,
        "created_at": created_at,
        "created_by": "ai_leader",
        "draft_id": draft["draft_id"],
        "use_case": parent.get("use_case") or use_case,
        "annotation_format": fmt,
        "classes": classes,
        "split_strategy": parent.get("split_strategy")
        or ("random" if parent_version else "manual"),
        "split_note": (
            "Splits inherited from the parent version; imported items: split chosen explicitly "
            "by the AI Leader."
            if parent_version
            else "Initial version: split chosen explicitly by the AI Leader for each image."
        ),
        "synthetic": bool(parent.get("synthetic", False)),
        "counts": counts(items, classes),
        "changes": stats,
        "evaluation_reference_changed": bool(evaluation_changes),
        "evaluation_changes": evaluation_changes,
        "excluded_items": excluded,
        "split_fingerprints": split_fingerprints(items),
        "items": items,
    }
    return manifest, plan


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n").encode()


# --------------------------------------------------------------------------- read models


class UsedBy(BaseModel):
    model_id: str | None = None
    model_version: str
    run_id: str | None = None


class DatasetVersionSummary(BaseModel):
    version: str
    ref: DatasetRef
    uri: str
    schema_version: int
    parent_version: str | None = None
    parent_manifest_sha256: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    use_case: str | None = None
    annotation_format: str
    classes: list[str]
    counts: dict[str, dict[str, int]]
    split_strategy: str
    split_fingerprints: dict[str, str]
    synthetic: bool
    description: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    changes: dict[str, int] | None = None
    evaluation_reference_changed: bool | None = None
    evaluation_changes: list[dict] = Field(default_factory=list)
    excluded_items: list[dict] = Field(default_factory=list)
    used_by: list[UsedBy] = Field(default_factory=list)
    locked: bool = False


class Incomplete(BaseModel):
    version: str
    state: Literal["publishing", "interrupted"]
    draft_id: str | None = None


class DraftSummary(BaseModel):
    draft_id: str
    parent_version: str
    status: str
    created_at: str
    updated_at: str
    n_changes: int
    n_imports: int
    target_version: str | None = None
    published_version: str | None = None


class DatasetIndex(BaseModel):
    model_id: str
    root: str
    name: str | None
    versions: list[DatasetVersionSummary]
    incomplete: list[Incomplete]
    drafts: list[DraftSummary]


class DatasetFamilySummary(BaseModel):
    dataset_id: str
    name: str
    use_case: str
    annotation_format: str
    classes: list[str]
    root: str
    synthetic: bool
    linked_models: list[str]
    version_count: int
    latest_version: str | None
    latest_images: int | None
    latest_splits: dict[str, int] | None
    last_published_at: str | None
    draft_count: int


@dataclass(frozen=True)
class DatasetScope:
    id: str
    dataset_root: str
    dataset_name: str
    argos_use_case: str
    dataset_tables: tuple[str, ...] = ()
    training_job: str | None = None
    synthetic: bool = True


class ItemPage(BaseModel):
    total: int
    offset: int
    limit: int
    facets: dict[str, dict[str, int]]
    items: list[dict]


class TableInfo(BaseModel):
    name: str
    columns: list[dict[str, str]]
    num_rows: int | None = None
    last_commit: str | None = None
    note: str


class TrainingDataset(BaseModel):
    job_name: str | None
    dataset_dir: str | None
    dataset_version: str | None
    source: str


class PublishJob(BaseModel):
    job_id: str
    model_id: str
    draft_id: str
    version: str
    state: Literal["running", "succeeded", "failed"] = "running"
    phase: str = "starting"
    done: int = 0
    total: int = 0
    error: str | None = None
    manifest_sha256: str | None = None
    started_at: str = Field(default_factory=now)
    ended_at: str | None = None
    resumed: bool = False


class ImportResult(BaseModel):
    name: str
    accepted: bool
    reason: str | None = None
    sha256: str | None = None


# --------------------------------------------------------------------------- store


def _already_exists(exc: BaseException) -> bool:
    return "AlreadyExists" in type(exc).__name__ or "ALREADY_EXISTS" in str(exc)


class DatasetStore:
    """Dataset operations of one connector (same Databricks client, same read cache)."""

    def __init__(self, connector: DatabricksConnector) -> None:
        self.c = connector
        self._manifests: dict[tuple[str, str], tuple[str, dict]] = {}  # immutable: kept
        self._images: OrderedDict[str, bytes] = OrderedDict()
        self._times: dict[str, str | None] = {}
        self._images_lock = threading.Lock()
        self._draft_locks: dict[str, threading.Lock] = {}
        self._jobs: dict[str, PublishJob] = {}
        self._jobs_lock = threading.Lock()
        self._family_records: dict[str, dict] = {}
        self._family_lock = threading.Lock()

    # ------------------------------------------------------------------ Files API helpers

    @property
    def w(self):
        return self.c.w

    @property
    def catalog_root(self) -> str:
        configured = self.c.settings.dataset_catalog_root
        if configured:
            return configured.rstrip("/")
        legacy = next((m.dataset_root for m in self.c.settings.models if m.dataset_root), None)
        if not legacy:
            raise InvalidDatasetRequest("ARGOS_DBX_DATASET_CATALOG_ROOT is required")
        return f"{legacy.rstrip('/')}/_families"

    def _family(self, dataset_id: str) -> dict:
        check_version_name(dataset_id)
        with self._family_lock:
            record = self._family_records.get(dataset_id)
        if record is None:
            raw = self._download(f"{self.catalog_root}/{dataset_id}/family.json")
            record = json.loads(raw)
            if record.get("dataset_id") != dataset_id:
                raise DatabricksConnectorError("family metadata names another dataset")
            with self._family_lock:
                self._family_records[dataset_id] = record
        return record

    def _legacy(self) -> dict[str, list[ManagedModel]]:
        families: dict[str, list[ManagedModel]] = {}
        root_ids: dict[str, str] = {}
        for model in self.c.settings.models:
            root = model.dataset_root
            if not root or root.rstrip("/").startswith(self.catalog_root + "/"):
                continue
            dataset_id = root_ids.setdefault(root, model.dataset_name or model.id)
            families.setdefault(dataset_id, []).append(model)
        return families

    def create_family(
        self,
        dataset_id: str,
        name: str,
        use_case: str,
        classes: list[str],
        synthetic: bool,
        description: str | None = None,
    ) -> dict:
        """Register a family in the existing Volume without creating a model or a version."""
        check_version_name(dataset_id)
        name = name.strip()
        if not name or len(name) > 100:
            raise InvalidDatasetRequest("dataset name must contain 1 to 100 characters")
        if use_case not in ("quality", "workstation", "safety"):
            raise InvalidDatasetRequest("use_case must be quality, workstation or safety")
        if not classes or len(classes) > 50 or len(classes) != len(set(classes)):
            raise InvalidDatasetRequest("classes must be unique and contain 1 to 50 labels")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label) for label in classes):
            raise InvalidDatasetRequest("class labels must be simple path-safe names")
        if dataset_id in self._legacy():
            raise ConflictError("dataset id already belongs to a configured legacy family")
        root = f"{self.catalog_root}/{dataset_id}"
        if self._exists(f"{root}/family.json") or self._list(root):
            raise ConflictError("dataset family folder already contains data")
        record = {
            "dataset_id": dataset_id,
            "name": name,
            "use_case": use_case,
            "annotation_format": "classification",
            "classes": classes,
            "synthetic": synthetic,
            "description": description,
            "created_at": now(),
            "version_count": 0,
            "latest_version": None,
            "latest_images": None,
            "latest_splits": None,
            "last_published_at": None,
        }
        self.c._call(lambda: self.w.files.create_directory(root), root)
        self._upload(f"{root}/family.json", manifest_bytes(record))
        with self._family_lock:
            self._family_records[dataset_id] = record
        self.c.reads.invalidate("dataset_catalog")
        return record

    def family_index(self, dataset_id: str) -> DatasetIndex:
        return self.index(self.scope_id(dataset_id))

    def _invalidate(self, model_id: str) -> None:
        self.c.reads.invalidate(f"datasets:{model_id}")
        self.c.reads.invalidate("dataset_catalog")

    def catalog(self) -> list[DatasetFamilySummary]:
        return self.c._cached("dataset_catalog", self._catalog)

    def _catalog(self) -> list[DatasetFamilySummary]:
        legacy = self._legacy()
        ids = list(legacy)
        for entry in self._list(self.catalog_root):
            dataset_id = PurePosixPath(entry.path.rstrip("/")).name
            if entry.is_directory and VERSION_RE.match(dataset_id):
                if dataset_id in legacy:
                    raise ConflictError(f"dataset id {dataset_id} conflicts with a legacy family")
                ids.append(dataset_id)
        # Bounded parallel reads keep tens of independent families within the existing
        # request budget. The request context (fresh/cache) must reach each worker.
        with ThreadPoolExecutor(max_workers=min(4, max(len(ids), 1))) as pool:
            jobs = [
                pool.submit(
                    contextvars.copy_context().run,
                    self._catalog_one,
                    dataset_id,
                    legacy.get(dataset_id, []),
                )
                for dataset_id in ids
            ]
            out = [job.result() for job in jobs]
        return sorted(out, key=lambda item: item.name.casefold())

    def _catalog_one(self, dataset_id: str, models: list[ManagedModel]) -> DatasetFamilySummary:
        record = None if models else self._family(dataset_id)
        root = models[0].dataset_root if models else f"{self.catalog_root}/{dataset_id}"
        linked = [m.id for m in self.c.settings.models if m.dataset_root == root]
        # New families keep a small catalogue projection. A missing/stale projection
        # falls back to the immutable manifests, which remain the source of truth.
        entries = self._list(root) if record else []
        folders = [
            e
            for e in entries
            if e.is_directory and VERSION_RE.match(PurePosixPath(e.path.rstrip("/")).name)
        ]
        summary_ok = record is not None and record.get("version_count") == len(folders)
        index = None if summary_ok else self.family_index(dataset_id)
        latest = index.versions[-1] if index and index.versions else None
        drafts = self._drafts(self._managed(f"family:{dataset_id}")) if summary_ok else None
        return DatasetFamilySummary(
            dataset_id=dataset_id,
            name=record["name"] if record else models[0].dataset_name or dataset_id,
            use_case=record["use_case"] if record else models[0].argos_use_case,
            annotation_format=latest.annotation_format
            if latest
            else record["annotation_format"]
            if record
            else "unknown",
            classes=latest.classes if latest else record["classes"] if record else [],
            root=root,
            synthetic=latest.synthetic
            if latest
            else record["synthetic"]
            if record
            else models[0].synthetic,
            linked_models=linked,
            version_count=record["version_count"] if summary_ok else len(index.versions),
            latest_version=record["latest_version"]
            if summary_ok
            else latest.version
            if latest
            else None,
            latest_images=record["latest_images"]
            if summary_ok
            else latest.ref.num_samples
            if latest
            else None,
            latest_splits=record["latest_splits"]
            if summary_ok
            else latest.ref.splits
            if latest
            else None,
            last_published_at=record["last_published_at"]
            if summary_ok
            else latest.created_at
            if latest
            else None,
            draft_count=sum(
                d.status != "published" for d in (drafts if summary_ok else index.drafts)
            ),
        )

    def _refresh_family_summary(self, model_id: str) -> None:
        """Best-effort catalogue projection after a committed independent version."""
        if not model_id.startswith("family:"):
            return
        dataset_id = model_id.removeprefix("family:")
        try:
            self._invalidate(model_id)
            index = self.index(model_id)
            latest = index.versions[-1]
            record = {
                **self._family(dataset_id),
                "version_count": len(index.versions),
                "latest_version": latest.version,
                "latest_images": latest.ref.num_samples,
                "latest_splits": latest.ref.splits,
                "last_published_at": latest.created_at,
            }
            self._upload(
                f"{self.catalog_root}/{dataset_id}/family.json",
                manifest_bytes(record),
                overwrite=True,
            )
            with self._family_lock:
                self._family_records[dataset_id] = record
        except Exception:  # noqa: BLE001 - published manifest stays valid; catalogue falls back
            logging.getLogger(__name__).warning(
                "dataset family catalogue projection could not be updated", exc_info=True
            )

    def scope_id(self, dataset_id: str) -> str:
        check_version_name(dataset_id)
        legacy = self._legacy().get(dataset_id)
        if legacy:
            return legacy[0].id
        self._family(dataset_id)
        return f"family:{dataset_id}"

    def _managed(self, model_id: str) -> ManagedModel | DatasetScope:
        if model_id.startswith("family:"):
            dataset_id = model_id.removeprefix("family:")
            record = self._family(dataset_id)
            return DatasetScope(
                id=model_id,
                dataset_root=f"{self.catalog_root}/{dataset_id}",
                dataset_name=record["name"],
                argos_use_case=record["use_case"],
                synthetic=record["synthetic"],
            )
        managed = self.c.managed(model_id)
        if not managed.dataset_root:
            raise ResourceNotFoundError(f"no dataset configured for {model_id}")
        return managed

    def _download(self, path: str) -> bytes:
        return self.c._call(lambda: self.w.files.download(path).contents.read(), path)

    def _upload(self, path: str, data: bytes, overwrite: bool = False) -> None:
        def op():
            try:
                self.w.files.upload(path, io.BytesIO(data), overwrite=overwrite)
            except Exception as exc:
                if _already_exists(exc):
                    raise ConflictError(f"{path} already exists") from exc
                raise

        self.c._call(op, path)

    def _list(self, path: str) -> list[Any]:
        try:
            return self.c._call(lambda: list(self.w.files.list_directory_contents(path)), path)
        except ResourceNotFoundError:
            return []

    def _exists(self, path: str) -> bool:
        try:
            self.c._call(lambda: self.w.files.get_metadata(path), path)
            return True
        except ResourceNotFoundError:
            return False

    # ------------------------------------------------------------------ manifests

    def manifest(self, model_id: str, version: str) -> tuple[str, dict]:
        """(sha256 of the manifest bytes, manifest). Cached for the process lifetime: a
        published version never changes."""
        managed = self._managed(model_id)
        check_version_name(version)
        key = (managed.dataset_root, version)
        if key not in self._manifests:
            raw = self._download(f"{managed.dataset_root}/{version}/manifest.json")
            data = json.loads(raw)
            if data.get("dataset_version") != version:
                raise DatabricksConnectorError(f"manifest of {version} names another version")
            self._manifests[key] = (sha256(raw), data)
        return self._manifests[key]

    def _used_by(self, model_id: str) -> dict[str, list[UsedBy]]:
        """manifest sha256 -> model versions trained on it (MLflow run tags, cached)."""
        out: dict[str, list[UsedBy]] = {}
        root = self._managed(model_id).dataset_root
        for model in self.c.settings.models:
            if model.dataset_root != root:
                continue
            for vs in self.c.model_status(model.id).versions:
                run_id = vs.version.run_id
                if not run_id:
                    continue
                tag = self.c.get_run(run_id).tags.get("argos.manifest_sha256")
                if tag:
                    out.setdefault(tag, []).append(
                        UsedBy(model_id=model.id, model_version=vs.version.version, run_id=run_id)
                    )
        return out

    def _summary(
        self, managed: ManagedModel, version: str, sha: str, m: dict, used: dict
    ) -> DatasetVersionSummary:
        items = m.get("items", [])
        classes = list(m.get("classes") or sorted({i.get("label", "?") for i in items}))
        c = m.get("counts") if m.get("schema_version") == 2 else counts(items, classes)
        uri = f"{managed.dataset_root}/{version}"
        strategy = m.get("split_strategy") or "random"
        ref = DatasetRef(
            name=managed.dataset_name or managed.id,
            version=version,
            uri=uri,
            manifest_sha256=sha,
            num_samples=len(items),
            splits={s: sum(c.get(s, {}).values()) for s in SPLITS},
            split_strategy=strategy
            if strategy in ("by_sequence", "by_time", "by_station", "random")
            else "random",
            confidential=not m.get("synthetic", False),
            classes=classes,
        )
        provenance = {
            k: m[k]
            for k in (
                "generator",
                "seed",
                "image_size",
                "mode",
                "split_ratios",
                "draft_id",
                "split_note",
            )
            if k in m
        }
        users = used.get(sha, [])
        return DatasetVersionSummary(
            version=version,
            ref=ref,
            uri=uri,
            schema_version=int(m.get("schema_version", 1)),
            parent_version=m.get("parent_version"),
            parent_manifest_sha256=m.get("parent_manifest_sha256"),
            created_at=m.get("created_at"),
            created_by=m.get("created_by"),
            use_case=m.get("use_case") or managed.argos_use_case,
            annotation_format=annotation_format(m),
            classes=classes,
            counts=c,
            split_strategy=strategy if m.get("split_strategy") else "random (stratified, seeded)",
            split_fingerprints=m.get("split_fingerprints") or split_fingerprints(items),
            synthetic=bool(m.get("synthetic", False)),
            description=m.get("description"),
            provenance=provenance,
            changes=m.get("changes"),
            evaluation_reference_changed=m.get("evaluation_reference_changed"),
            evaluation_changes=m.get("evaluation_changes", []),
            excluded_items=m.get("excluded_items", []),
            used_by=users,
            locked=bool(users),
        )

    # ------------------------------------------------------------------ reads

    def index(self, model_id: str) -> DatasetIndex:
        return self.c._cached(f"datasets:{model_id}", lambda: self._index(model_id))

    def _index(self, model_id: str) -> DatasetIndex:
        managed = self._managed(model_id)
        root = managed.dataset_root
        # Independent reads in parallel; each task runs in a COPY of the request context
        # (fresh flag, time budget and freshness record are context variables).
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [
                pool.submit(contextvars.copy_context().run, fn, *args)
                for fn, args in (
                    (self._list, (root,)),
                    (self._list, (f"{root}/_locks",)),
                    (self._drafts, (managed,)),
                    (self._used_by, (model_id,)),
                )
            ]
            entries, lock_entries, drafts, used = (j.result() for j in jobs)
        locks = {PurePosixPath(e.path.rstrip("/")).name.removesuffix(".lock") for e in lock_entries}
        targets = {d.target_version: d.draft_id for d in drafts if d.status == "publishing"}
        versions, incomplete = [], []
        for entry in entries:
            name = PurePosixPath(entry.path.rstrip("/")).name
            if not entry.is_directory or name in RESERVED or not VERSION_RE.match(name):
                continue
            try:
                sha, m = self.manifest(model_id, name)
            except ResourceNotFoundError:
                incomplete.append(
                    Incomplete(
                        version=name,
                        state="publishing" if name in locks else "interrupted",
                        draft_id=targets.get(name),
                    )
                )
                continue
            if not m.get("created_at"):
                # DBX-00 manifests carry no date: use the manifest file's real upload time.
                m = {**m, "created_at": self._file_time(f"{root}/{name}", "manifest.json")}
            versions.append(self._summary(managed, name, sha, m, used))
        versions.sort(key=lambda v: v.created_at or "")
        return DatasetIndex(
            model_id=model_id,
            root=root,
            name=managed.dataset_name,
            versions=versions,
            incomplete=incomplete,
            drafts=drafts,
        )

    def _file_time(self, folder: str, file: str) -> str | None:
        """Upload time of a file of an immutable version (cached for the process)."""
        key = f"{folder}/{file}"
        if key not in self._times:
            entry = next(
                (e for e in self._list(folder) if e.path.rstrip("/").endswith("/" + file)), None
            )
            self._times[key] = _iso(getattr(entry, "last_modified", None)) if entry else None
        return self._times[key]

    def version(self, model_id: str, version: str) -> DatasetVersionSummary:
        found = next((v for v in self.index(model_id).versions if v.version == version), None)
        if found is None:
            raise ResourceNotFoundError(f"dataset version {version} not found")
        return found

    def items(
        self,
        model_id: str,
        version: str,
        split: str | None = None,
        label: str | None = None,
        review: str | None = None,
        query: str | None = None,
        offset: int = 0,
        limit: int = 24,
    ) -> ItemPage:
        _, m = self.manifest(model_id, version)
        items = m.get("items", [])
        facets = {
            "split": _facet(items, lambda i: i.get("split")),
            "label": _facet(items, lambda i: i.get("label")),
            "review": _facet(items, lambda i: i.get("review") or "none"),
        }
        selected = [
            i
            for i in items
            if (not split or i.get("split") == split)
            and (not label or i.get("label") == label)
            and (not review or (i.get("review") or "none") == review)
            and (not query or query.lower() in i.get("file", "").lower())
        ]
        limit = max(1, min(limit, PAGE_MAX))
        offset = max(0, offset)
        return ItemPage(
            total=len(selected),
            offset=offset,
            limit=limit,
            facets=facets,
            items=selected[offset : offset + limit],
        )

    def image(self, model_id: str, version: str, file: str) -> tuple[bytes, str]:
        """Bytes of an image LISTED in the version manifest (whitelist), never a free path."""
        file = safe_relative_file(file)
        _, m = self.manifest(model_id, version)
        if file not in {i["file"] for i in m.get("items", [])}:
            raise ResourceNotFoundError("image not listed in this version")
        path = f"{self._managed(model_id).dataset_root}/{version}/{file}"
        return self._image_bytes(path), _content_type(file)

    def _image_bytes(self, path: str) -> bytes:
        with self._images_lock:
            if path in self._images:
                self._images.move_to_end(path)
                return self._images[path]
        data = self._download(path)
        if len(data) > MAX_SERVED_IMAGE_BYTES:
            raise ForbiddenOperationError("image too large to be served")
        with self._images_lock:
            self._images[path] = data
            while len(self._images) > 512:
                self._images.popitem(last=False)
        return data

    def tables(self, model_id: str) -> list[TableInfo]:
        managed = self._managed(model_id)
        return self.c._cached(
            f"dstables:{model_id}", lambda: [self._table(t) for t in managed.dataset_tables]
        )

    def _table(self, name: str) -> TableInfo:
        t = self.c._call(lambda: self.c.w.tables.get(name), name)
        props = t.properties or {}
        rows = props.get("spark.sql.statistics.numRows")
        commit = props.get("delta.lastCommitTimestamp")
        return TableInfo(
            name=name,
            columns=[{"name": col.name, "type": col.type_text} for col in (t.columns or [])],
            num_rows=int(rows) if rows else None,
            last_commit=datetime.fromtimestamp(int(commit) / 1000, UTC).isoformat()
            if commit
            else None,
            note="Delta mirror written by the training job (Unity Catalog metadata only, "
            "no SQL warehouse); the Volume manifests are the source of truth.",
        )

    def training_dataset(self, model_id: str) -> TrainingDataset:
        """Dataset the model's training job is REALLY configured with (job definition)."""
        managed = self.c.managed(model_id)
        return self.c._cached(
            f"trainingdataset:{model_id}", lambda: self._training_dataset(managed)
        )

    def _training_dataset(self, managed: ManagedModel) -> TrainingDataset:
        if not managed.training_job:
            return TrainingDataset(
                job_name=None, dataset_dir=None, dataset_version=None, source="no training job"
            )
        job = next(
            iter(self.c._call(lambda: list(self.w.jobs.list(name=managed.training_job)), "job")),
            None,
        )
        if job is None:
            return TrainingDataset(
                job_name=managed.training_job,
                dataset_dir=None,
                dataset_version=None,
                source="job not found",
            )
        full = self.c._call(lambda: self.w.jobs.get(job.job_id), "job")
        for task in (full.settings.tasks or []) if full.settings else []:
            params = (task.notebook_task.base_parameters or {}) if task.notebook_task else {}
            try:
                args = json.loads(params.get("args", "[]"))
            except ValueError:
                args = []
            if "--dataset-dir" in args and args.index("--dataset-dir") + 1 < len(args):
                path = args[args.index("--dataset-dir") + 1]
                return TrainingDataset(
                    job_name=managed.training_job,
                    dataset_dir=path,
                    dataset_version=PurePosixPath(path).name,
                    source="job definition (--dataset-dir)",
                )
        return TrainingDataset(
            job_name=managed.training_job,
            dataset_dir=None,
            dataset_version=None,
            source="no --dataset-dir in the job definition",
        )

    # ------------------------------------------------------------------ drafts

    def _draft_path(self, managed: ManagedModel, draft_id: str) -> str:
        if not DRAFT_ID_RE.match(draft_id):
            raise InvalidDatasetRequest("invalid draft id")
        return f"{managed.dataset_root}/_drafts/{draft_id}"

    def _drafts(self, managed: ManagedModel) -> list[DraftSummary]:
        out = []
        for entry in self._list(f"{managed.dataset_root}/_drafts"):
            draft_id = PurePosixPath(entry.path.rstrip("/")).name
            if not entry.is_directory or not DRAFT_ID_RE.match(draft_id):
                continue
            try:
                d = self._read_draft(managed, draft_id)
            except ResourceNotFoundError:
                continue
            out.append(_draft_summary(d))
        out.sort(key=lambda d: d.created_at, reverse=True)
        return out

    def _read_draft(self, managed: ManagedModel, draft_id: str) -> dict:
        return json.loads(self._download(f"{self._draft_path(managed, draft_id)}/draft.json"))

    def _write_draft(self, managed: ManagedModel, draft: dict, create: bool = False) -> None:
        draft["updated_at"] = now()
        self._upload(
            f"{self._draft_path(managed, draft['draft_id'])}/draft.json",
            manifest_bytes(draft),
            overwrite=not create,
        )

    def _lock_for(self, draft_id: str) -> threading.Lock:
        with self._jobs_lock:
            return self._draft_locks.setdefault(draft_id, threading.Lock())

    def get_draft(self, model_id: str, draft_id: str) -> dict:
        return self._read_draft(self._managed(model_id), draft_id)

    def _parent(self, model_id: str, parent_version: str) -> tuple[str | None, dict]:
        if parent_version:
            return self.manifest(model_id, parent_version)
        if not model_id.startswith("family:") or self.index(model_id).versions:
            raise InvalidDatasetRequest("a published parent version is required")
        record = self._family(model_id.removeprefix("family:"))
        return None, {
            "dataset_version": None,
            "items": [],
            "classes": record["classes"],
            "synthetic": record["synthetic"],
            "annotation_format": record["annotation_format"],
            "use_case": record["use_case"],
            "description": record.get("description"),
        }

    def create_draft(self, model_id: str, parent_version: str | None) -> dict:
        managed = self._managed(model_id)
        parent_sha, _ = self._parent(model_id, parent_version or "")
        draft = {
            "schema_version": 1,
            "draft_id": uuid.uuid4().hex[:12],
            "model_id": model_id,
            "parent_version": parent_version or "",
            "parent_manifest_sha256": parent_sha or "",
            "status": "open",
            "created_at": now(),
            "created_by": "ai_leader",
            "changes": {},
            "imports": [],
        }
        self._write_draft(managed, draft, create=True)
        self._invalidate(model_id)
        return draft

    def _open_draft(self, managed: ManagedModel, draft_id: str) -> dict:
        draft = self._read_draft(managed, draft_id)
        if draft.get("status") != "open":
            raise ConflictError(f"draft is {draft.get('status')}: it can no longer be modified")
        return draft

    def update_items(self, model_id: str, draft_id: str, changes: list[dict]) -> dict:
        managed = self._managed(model_id)
        with self._lock_for(draft_id):
            draft = self._open_draft(managed, draft_id)
            _, parent = self._parent(model_id, draft["parent_version"])
            by_file = {i["file"]: i for i in parent["items"]}
            fmt = annotation_format(parent)
            classes = set(parent.get("classes") or [])
            for change in changes:
                file, action = change.get("file"), change.get("action")
                if file not in by_file:
                    raise InvalidDatasetRequest("file not in the parent version")
                if action == "reset":
                    draft["changes"].pop(file, None)
                elif action == "validate":
                    draft["changes"][file] = {"action": "validate", "note": change.get("note")}
                elif action == "exclude":
                    draft["changes"][file] = {"action": "exclude", "note": change.get("note")}
                elif action == "relabel":
                    if fmt != "classification":
                        raise InvalidDatasetRequest(
                            "label correction is only supported for classification"
                        )
                    label = change.get("label")
                    if label not in classes:
                        raise InvalidDatasetRequest("label not among the dataset classes")
                    if label == by_file[file]["label"]:
                        raise InvalidDatasetRequest("same label as the current one: use validate")
                    draft["changes"][file] = {
                        "action": "relabel",
                        "label": label,
                        "note": change.get("note"),
                    }
                else:
                    raise InvalidDatasetRequest(
                        "action must be validate, relabel, exclude or reset"
                    )
            self._write_draft(managed, draft)
        self._invalidate(model_id)
        return draft

    def import_files(
        self,
        model_id: str,
        draft_id: str,
        files: Iterable[tuple[str, Any]],
        label: str,
        split: str,
        synthetic_attested: bool,
        group: str | None = None,
    ) -> list[ImportResult]:
        """Bounded import of SYNTHETIC images into a draft. ``files`` yields (name, binary
        stream); each file is read on its own (never all in memory). ``group`` (optional)
        records the source group / burst of the batch: kept in the published manifest so
        that related images can be kept in one split (leakage control)."""
        if group is not None and not GROUP_RE.match(group):
            raise InvalidDatasetRequest("invalid group (letters, digits, - _ . and spaces, 1-80)")
        from PIL import Image, UnidentifiedImageError

        if not synthetic_attested:
            raise InvalidDatasetRequest("synthetic data attestation required")
        if split not in SPLITS:
            raise InvalidDatasetRequest("split must be train, validation or test")
        managed = self._managed(model_id)
        results: list[ImportResult] = []
        with self._lock_for(draft_id):
            draft = self._open_draft(managed, draft_id)
            _, parent = self._parent(model_id, draft["parent_version"])
            if annotation_format(parent) != "classification":
                raise InvalidDatasetRequest("import is only supported for classification datasets")
            if label not in set(parent.get("classes") or []):
                raise InvalidDatasetRequest("label not among the dataset classes")
            known = {i["sha256"] for i in parent["items"]} | {i["sha256"] for i in draft["imports"]}
            total, count = 0, 0
            for name, stream in files:
                count += 1
                if count > MAX_IMPORT_FILES:
                    results.append(
                        ImportResult(name=name, accepted=False, reason="too many files (max 50)")
                    )
                    continue
                data = stream.read(MAX_IMPORT_FILE_BYTES + 1)
                total += len(data)
                if len(data) > MAX_IMPORT_FILE_BYTES:
                    results.append(
                        ImportResult(name=name, accepted=False, reason="file too large (max 2 MB)")
                    )
                    continue
                if total > MAX_IMPORT_REQUEST_BYTES:
                    results.append(
                        ImportResult(
                            name=name, accepted=False, reason="request too large (max 25 MB)"
                        )
                    )
                    continue
                try:
                    with Image.open(io.BytesIO(data)) as img:
                        fmt, (width, height) = img.format, img.size
                        img.verify()
                except (UnidentifiedImageError, OSError, ValueError):
                    results.append(
                        ImportResult(name=name, accepted=False, reason="not a valid image")
                    )
                    continue
                if fmt not in ("PNG", "JPEG"):
                    results.append(
                        ImportResult(name=name, accepted=False, reason="format must be PNG or JPEG")
                    )
                    continue
                if max(width, height) > MAX_IMAGE_SIDE:
                    results.append(
                        ImportResult(name=name, accepted=False, reason="image larger than 4096 px")
                    )
                    continue
                digest = sha256(data)
                if digest in known:
                    results.append(
                        ImportResult(
                            name=name,
                            accepted=False,
                            reason="duplicate image (same SHA-256)",
                            sha256=digest,
                        )
                    )
                    continue
                ext = ".png" if fmt == "PNG" else ".jpg"
                stored = f"files/{digest}{ext}"
                try:
                    self._upload(f"{self._draft_path(managed, draft_id)}/{stored}", data)
                except ConflictError:
                    pass  # same name = same SHA-256 = same bytes (idempotent retry)
                known.add(digest)
                draft["imports"].append(
                    {
                        "stored": stored,
                        "sha256": digest,
                        "ext": ext,
                        "format": fmt,
                        "width": width,
                        "height": height,
                        "size": len(data),
                        "label": label,
                        "split": split,
                        "original_name": PurePosixPath(name.replace("\\", "/")).name[:120],
                        "imported_at": now(),
                        "synthetic_attested": True,
                        **({"group": group} if group else {}),
                    }
                )
                results.append(ImportResult(name=name, accepted=True, sha256=digest))
            if any(r.accepted for r in results):
                self._write_draft(managed, draft)
        self._invalidate(model_id)
        return results

    def remove_import(self, model_id: str, draft_id: str, digest: str) -> dict:
        managed = self._managed(model_id)
        with self._lock_for(draft_id):
            draft = self._open_draft(managed, draft_id)
            draft["imports"] = [i for i in draft["imports"] if i["sha256"] != digest]
            self._write_draft(managed, draft)
        self._invalidate(model_id)
        return draft

    def draft_image(self, model_id: str, draft_id: str, digest: str) -> tuple[bytes, str]:
        managed = self._managed(model_id)
        draft = self._read_draft(managed, draft_id)
        imp = next((i for i in draft["imports"] if i["sha256"] == digest), None)
        if imp is None:
            raise ResourceNotFoundError("image not in this draft")
        return self._image_bytes(
            f"{self._draft_path(managed, draft_id)}/{imp['stored']}"
        ), _content_type(imp["stored"])

    def delete_draft(self, model_id: str, draft_id: str) -> None:
        """Delete an OPEN or PUBLISHED draft (only its own folder). A draft being published
        (or interrupted) is kept: it is needed to resume."""
        managed = self._managed(model_id)
        with self._lock_for(draft_id):
            draft = self._read_draft(managed, draft_id)
            if draft.get("status") == "publishing":
                raise ConflictError("draft is being published: resume or finish it first")
            base = self._draft_path(managed, draft_id)
            for imp in draft.get("imports", []):
                try:
                    self.c._call(
                        lambda p=f"{base}/{imp['stored']}": self.w.files.delete(p), "draft file"
                    )
                except ResourceNotFoundError:
                    pass
            self.c._call(lambda: self.w.files.delete(f"{base}/draft.json"), "draft")
            for folder in (f"{base}/files", base):
                try:
                    self.c._call(lambda f=folder: self.w.files.delete_directory(f), "draft folder")
                except (ResourceNotFoundError, DatabricksConnectorError):
                    pass  # absent or not empty: never forced
        self._invalidate(model_id)

    # ------------------------------------------------------------------ publication

    def job(self, job_id: str) -> PublishJob:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ResourceNotFoundError("publication job not found")
        return job

    def start_publish(
        self, model_id: str, draft_id: str, version: str, background: bool = True
    ) -> PublishJob:
        managed = self._managed(model_id)
        check_version_name(version)
        with self._lock_for(draft_id):
            draft = self._read_draft(managed, draft_id)
            status = draft.get("status")
            resumed = status == "publishing"
            if status == "published":
                raise ConflictError(f"draft already published as {draft.get('published_version')}")
            if resumed and draft.get("target_version") != version:
                raise ConflictError(f"draft is being published as {draft.get('target_version')}")
            if not draft["changes"] and not draft["imports"]:
                raise InvalidDatasetRequest("nothing to publish: the draft has no change")
            root = managed.dataset_root
            if self._exists(f"{root}/{version}/manifest.json"):
                raise ConflictError(f"version {version} already exists")
            folder_exists = any(
                PurePosixPath(e.path.rstrip("/")).name == version
                for e in self._list(root)
                if e.is_directory
            )
            if folder_exists and not resumed:
                raise ConflictError(
                    f"folder {version} exists without manifest "
                    "(interrupted publication of another draft)"
                )
            with self._jobs_lock:
                if any(j.version == version and j.state == "running" for j in self._jobs.values()):
                    raise ConflictError(f"version {version} is already being published")
                job = PublishJob(
                    job_id=uuid.uuid4().hex[:12],
                    model_id=model_id,
                    draft_id=draft_id,
                    version=version,
                    resumed=resumed,
                )
                self._jobs[job.job_id] = job
        if background:
            threading.Thread(
                target=self._publish, args=(job,), name=f"publish-{version}", daemon=True
            ).start()
        else:
            self._publish(job)
        return job

    def _set(self, job: PublishJob, **fields) -> None:
        with self._jobs_lock:
            for key, value in fields.items():
                setattr(job, key, value)

    def _publish(self, job: PublishJob) -> None:
        managed = self._managed(job.model_id)
        root, version = managed.dataset_root, job.version
        lock_path = f"{root}/_locks/{version}.lock"
        token = uuid.uuid4().hex
        locked = False
        try:
            self._set(job, phase="lock")
            self._acquire_lock(lock_path, token, job.draft_id)
            locked = True
            with self._lock_for(job.draft_id):
                draft = self._read_draft(managed, job.draft_id)
                parent_sha, parent = self._parent(job.model_id, draft["parent_version"])
                if (parent_sha or "") != draft["parent_manifest_sha256"]:
                    raise ConflictError("parent manifest changed since the draft was created")
                if draft.get("status") != "publishing":
                    draft.update(
                        status="publishing", target_version=version, publish_started_at=now()
                    )
                    self._write_draft(managed, draft)
            self._invalidate(job.model_id)
            manifest, plan = build_manifest(
                parent,
                parent_sha,
                draft,
                version,
                draft["publish_started_at"],
                managed.argos_use_case,
            )
            draft_base = self._draft_path(managed, job.draft_id)
            src_base = {"parent": f"{root}/{draft['parent_version']}", "draft": draft_base}

            self._set(job, phase="copy", done=0, total=len(plan))
            self._parallel(
                job, plan, lambda p: self._copy(src_base[p["source"]], p, f"{root}/{version}")
            )
            self._set(job, phase="verify", done=0, total=len(plan))
            self._parallel(
                job, plan, lambda p: self._verify(f"{root}/{version}/{p['dst']}", p["sha256"])
            )

            self._set(job, phase="manifest", done=0, total=1)
            raw = manifest_bytes(manifest)
            self._upload(f"{root}/{version}/manifest.json", raw)  # LAST write, never overwrites
            if sha256(self._download(f"{root}/{version}/manifest.json")) != sha256(raw):
                raise DatabricksConnectorError("manifest read back differs from the written one")
            with self._lock_for(job.draft_id):
                draft = self._read_draft(managed, job.draft_id)
                draft.update(
                    status="published",
                    published_version=version,
                    published_manifest_sha256=sha256(raw),
                    published_at=now(),
                )
                self._write_draft(managed, draft)
            self._refresh_family_summary(job.model_id)
            self._set(
                job,
                state="succeeded",
                phase="done",
                done=1,
                manifest_sha256=sha256(raw),
                ended_at=now(),
            )
        except Exception as exc:  # noqa: BLE001 - reported in the job, folder left for resume
            self._set(
                job, state="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}", ended_at=now()
            )
        finally:
            if locked:
                try:
                    self.c._call(lambda: self.w.files.delete(lock_path), "lock")
                except DatabricksConnectorError:
                    pass
            self._invalidate(job.model_id)

    def _acquire_lock(self, path: str, token: str, draft_id: str) -> None:
        body = manifest_bytes({"token": token, "draft_id": draft_id, "acquired_at": now()})
        try:
            self._upload(path, body)
        except ConflictError:
            current = json.loads(self._download(path))
            age = datetime.now(UTC) - datetime.fromisoformat(current["acquired_at"])
            if current.get("draft_id") != draft_id or age < LOCK_STALE_AFTER:
                raise ConflictError("this version is being published by another process") from None
            self._upload(path, body, overwrite=True)  # stale lock of the SAME draft: resume
        if json.loads(self._download(path)).get("token") != token:
            raise ConflictError("this version is being published by another process")

    def _parallel(self, job: PublishJob, plan: list[dict], fn) -> None:
        def run(p):
            fn(p)
            with self._jobs_lock:
                job.done += 1

        with ThreadPoolExecutor(max_workers=6) as pool:
            for future in [pool.submit(run, p) for p in plan]:
                future.result()

    def _copy(self, src_base: str, p: dict, dst_base: str) -> None:
        dst = f"{dst_base}/{p['dst']}"
        if self._exists(dst):  # resume: accept only the identical file
            if sha256(self._download(dst)) != p["sha256"]:
                raise ConflictError(f"{p['dst']} already exists with other content")
            return
        data = self._download(f"{src_base}/{p['src']}")
        if sha256(data) != p["sha256"]:
            raise ConflictError(f"source {p['src']} does not match its recorded SHA-256")
        self._upload(dst, data)

    def _verify(self, path: str, expected: str) -> None:
        if sha256(self._download(path)) != expected:
            raise ConflictError(f"{path} SHA-256 mismatch after upload")


# --------------------------------------------------------------------------- helpers


def _facet(items: list[dict], key) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        k = str(key(item))
        out[k] = out.get(k, 0) + 1
    return out


def _content_type(file: str) -> str:
    return "image/jpeg" if file.lower().endswith((".jpg", ".jpeg")) else "image/png"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC).isoformat(timespec="seconds")
    return str(value)


def _draft_summary(d: dict) -> DraftSummary:
    return DraftSummary(
        draft_id=d["draft_id"],
        parent_version=d["parent_version"],
        status=d.get("status", "open"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
        n_changes=len(d.get("changes", {})),
        n_imports=len(d.get("imports", [])),
        target_version=d.get("target_version"),
        published_version=d.get("published_version"),
    )


_STORE_LOCK = threading.Lock()


def dataset_store(connector: DatabricksConnector) -> DatasetStore:
    """One DatasetStore per connector (shares its client, read cache and manifest cache)."""
    store = getattr(connector, "_dataset_store", None)
    if store is None:
        with _STORE_LOCK:
            store = getattr(connector, "_dataset_store", None)
            if store is None:
                store = DatasetStore(connector)
                connector._dataset_store = store
    return store
