"""Package builder with fail-closed UC, run, artifact and Edge policy checks."""

from __future__ import annotations

from dataclasses import dataclass

from mlops.edge_packages.sources import ArtifactSource, MetadataSource, VersionEvidence
from mlops.edge_packages.store import PackageRecord, PackageStore
from visionhub.integration.mlops import ModelPackage


class PackageError(ValueError):
    pass


@dataclass(frozen=True)
class PackageInspection:
    evidence: VersionEvidence
    artifacts: tuple[str, ...]
    eligible: bool
    blockers: tuple[str, ...]


class PackageBuilder:
    def __init__(self, metadata: MetadataSource, artifacts: ArtifactSource, store: PackageStore):
        self.metadata = metadata
        self.artifacts = artifacts
        self.store = store

    def inspect(self, registered_model: str, version: str) -> PackageInspection:
        if not version.isdecimal():
            raise PackageError("model version must be numeric")
        evidence = self.metadata.resolve(registered_model, version)
        blockers = []
        if evidence.registered_model != registered_model or evidence.version != version:
            blockers.append("UC version identity mismatch")
        if not evidence.run_id:
            blockers.append("UC version has no associated MLflow run")
        if evidence.approval != "approved":
            blockers.append("UC version is not currently approved")
        if not evidence.authoritative:
            blockers.append("approval is local test evidence, not a UC approval")
        artifacts = tuple(self.metadata.artifact_inventory(evidence))
        return PackageInspection(evidence, artifacts, not blockers, tuple(blockers))

    def build(self, package: ModelPackage) -> PackageRecord:
        """Build a test-only package; real artifact transfer is deliberately not enabled."""
        inspection = self.inspect(package.model.registered_model, package.model.version)
        evidence = inspection.evidence
        # Local fixture decisions may exercise construction, but never imply UC approval.
        hard_blockers = [b for b in inspection.blockers if "local test evidence" not in b]
        if hard_blockers:
            raise PackageError("; ".join(hard_blockers))
        if package.model.mlflow_run_id != evidence.run_id:
            raise PackageError("ModelRef run does not match UC version run")
        if package.evaluation and package.evaluation.mlflow_run_id != evidence.run_id:
            raise PackageError("evaluation run does not match UC version run")
        run_hash = (evidence.run_tags or {}).get("argos.manifest_sha256")
        if not run_hash or package.dataset.manifest_sha256 != run_hash:
            raise PackageError("dataset manifest hash is missing or differs from the MLflow run")
        if package.artifact.uri not in inspection.artifacts:
            raise PackageError("artifact is absent from the MLflow run inventory")
        if self.artifacts.trust_level != "test_only":
            raise PackageError("remote artifact transfer has not been authorized")
        # Verify the source filename before copying. The store validates bytes after copying.
        source = self.artifacts.path(package.artifact.uri)
        if source.stat().st_size != package.artifact.size_bytes:
            raise PackageError("source artifact size mismatch")
        try:
            record = self.store.publish(
                package, source, trust_level="test_only", source_id=self.artifacts.source_id
            )
        except ValueError as exc:
            raise PackageError(str(exc)) from exc
        return record
