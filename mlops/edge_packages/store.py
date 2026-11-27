"""Immutable, content-addressed packages stored outside the source checkout."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Protocol

from mlops.delivery.validate_delivery import AllowedAdapter, validate_package
from visionhub.integration.mlops import ModelPackage


@dataclass(frozen=True)
class PackageRecord:
    digest: str
    folder: Path
    model: str
    version: str
    trust_level: str
    source_id: str

    @property
    def deployable(self) -> bool:
        return self.trust_level == "verified"


class PackageProvider(Protocol):
    """Read-only Core boundary. The Core must still authorize each station/request."""

    def get(self, digest: str, *, require_deployable: bool = True) -> PackageRecord: ...

    def find(self, model: str, version: str) -> list[PackageRecord]: ...


class PackageStore:
    def __init__(self, root: Path, allowed_adapters: dict[str, AllowedAdapter]):
        self.root = root.resolve()
        checkout = Path(__file__).resolve().parents[2]
        if self.root.is_relative_to(checkout):
            raise ValueError("package store must be outside the source checkout")
        self.root.mkdir(parents=True, exist_ok=True)
        self.allowed_adapters = allowed_adapters

    @staticmethod
    def _digest(manifest: bytes, artifact_hash: str, provenance: bytes) -> str:
        return hashlib.sha256(
            manifest + b"\n" + artifact_hash.encode("ascii") + b"\n" + provenance
        ).hexdigest()

    def publish(
        self,
        package: ModelPackage,
        artifact_path: Path,
        *,
        trust_level: str,
        source_id: str,
    ) -> PackageRecord:
        if trust_level not in {"test_only", "verified"} or not source_id:
            raise ValueError("source trust and identity are required")
        uri = package.artifact.uri
        relative = Path(uri)
        windows = PureWindowsPath(uri)
        if (
            not uri
            or relative.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ":" in uri
            or "\\" in uri
            or any(part in (".", "..") for part in relative.parts)
            or relative.parts[0] in {"model-package.json", "provenance.json"}
        ):
            raise ValueError("unsafe package artifact path")
        manifest = package.model_dump_json(indent=2).encode("utf-8")
        provenance = json.dumps(
            {"trust_level": trust_level, "source_id": source_id}, sort_keys=True
        ).encode("utf-8")
        digest = self._digest(manifest, package.artifact.sha256, provenance)
        destination = self.root / digest
        if destination.exists():
            existing = self.get(digest, require_deployable=False)
            if existing.trust_level != trust_level or existing.source_id != source_id:
                raise ValueError("existing digest has different provenance")
            return existing
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
        try:
            target = staging / package.artifact.uri
            target.parent.mkdir(parents=True, exist_ok=True)
            with artifact_path.open("rb") as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink, length=1024 * 1024)
            (staging / "model-package.json").write_bytes(manifest)
            (staging / "provenance.json").write_bytes(provenance)
            problems = validate_package(staging, self.allowed_adapters)
            if problems:
                raise ValueError("invalid package: " + "; ".join(problems))
            try:
                os.rename(staging, destination)
            except FileExistsError:
                return self.get(digest, require_deployable=False)
            return PackageRecord(
                digest,
                destination,
                package.model.registered_model,
                package.model.version,
                trust_level,
                source_id,
            )
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def get(self, digest: str, *, require_deployable: bool = True) -> PackageRecord:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid package digest")
        folder = self.root / digest
        if not folder.is_dir() or folder.is_symlink():
            raise FileNotFoundError(digest)
        manifest_path = folder / "model-package.json"
        provenance_path = folder / "provenance.json"
        if manifest_path.is_symlink() or provenance_path.is_symlink():
            raise ValueError("package metadata must not be symlinks")
        manifest = manifest_path.read_bytes()
        package = ModelPackage.model_validate_json(manifest)
        provenance_bytes = provenance_path.read_bytes()
        provenance = json.loads(provenance_bytes)
        if self._digest(manifest, package.artifact.sha256, provenance_bytes) != digest:
            raise ValueError("package digest mismatch")
        problems = validate_package(folder, self.allowed_adapters)
        if problems:
            raise ValueError("invalid package: " + "; ".join(problems))
        trust = provenance["trust_level"]
        if require_deployable and trust != "verified":
            raise PermissionError("test-only package cannot be distributed")
        return PackageRecord(
            digest,
            folder,
            package.model.registered_model,
            package.model.version,
            trust,
            provenance["source_id"],
        )

    def find(self, model: str, version: str) -> list[PackageRecord]:
        result = []
        for folder in self.root.iterdir():
            if len(folder.name) != 64 or not folder.is_dir():
                continue
            try:
                record = self.get(folder.name, require_deployable=False)
            except (ValueError, FileNotFoundError, PermissionError, KeyError):
                continue
            if record.model == model and record.version == version:
                result.append(record)
        return result
