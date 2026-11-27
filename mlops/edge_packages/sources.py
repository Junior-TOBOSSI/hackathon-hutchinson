"""Fresh registry metadata and explicitly authorized local artifact sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mlops.databricks.connector import DatabricksConnector


@dataclass(frozen=True)
class VersionEvidence:
    registered_model: str
    version: str
    run_id: str
    approval: str
    source: str
    authoritative: bool = False
    run_tags: dict[str, str] | None = None


class MetadataSource(Protocol):
    def resolve(self, registered_model: str, version: str) -> VersionEvidence: ...

    def artifact_inventory(self, evidence: VersionEvidence) -> list[str]: ...


class DatabricksMetadataSource:
    """Read UC and MLflow directly, bypassing cached API snapshots; never downloads weights."""

    def __init__(self, connector: DatabricksConnector):
        self.connector = connector

    def resolve(self, registered_model: str, version: str) -> VersionEvidence:
        if not version.isdecimal():
            raise ValueError("model version must be numeric")
        c = self.connector
        raw = c._call(
            lambda: c.mlflow.get_model_version(registered_model, version),
            f"model version {registered_model}/{version}",
        )
        run_id = raw.run_id or ""
        if not run_id:
            raise ValueError("UC model version has no associated MLflow run")
        run = c._call(lambda: c.mlflow.get_run(run_id), f"run {run_id}")
        if run.info.run_id != run_id:
            raise ValueError("MLflow run identity mismatch")
        return VersionEvidence(
            registered_model=str(raw.name),
            version=str(raw.version),
            run_id=run_id,
            approval=dict(raw.tags or {}).get("argos_approval", ""),
            source=str(getattr(raw, "source", "") or ""),
            authoritative=True,
            run_tags=dict(run.data.tags or {}),
        )

    def artifact_inventory(self, evidence: VersionEvidence) -> list[str]:
        """List run and MLflow 3 logged-model files, with their source namespaces."""
        c = self.connector
        result: list[str] = []
        pending = [""]
        while pending:
            prefix = pending.pop()
            entries = c._call(
                lambda p=prefix: c.mlflow.list_artifacts(evidence.run_id, p),
                f"artifact inventory {evidence.run_id}/{prefix}",
            )
            for entry in entries:
                if entry.is_dir:
                    pending.append(entry.path)
                else:
                    result.append(f"run/{entry.path}")
            if len(result) + len(pending) > 1000:
                raise ValueError("artifact inventory exceeds the safety limit")
        if evidence.source.startswith("models:/m-"):
            import mlflow

            model_id = evidence.source.removeprefix("models:/")
            model = c._call(lambda: c.mlflow.get_logged_model(model_id), model_id)
            if model.source_run_id != evidence.run_id or model.model_id != model_id:
                raise ValueError("logged model does not belong to the UC version run")
            root = model.artifact_location.rstrip("/")
            pending = [""]
            while pending:
                prefix = pending.pop()
                uri = root + ("/" + prefix if prefix else "")
                entries = c._call(
                    lambda u=uri: mlflow.artifacts.list_artifacts(artifact_uri=u),
                    f"logged model inventory {model_id}/{prefix}",
                )
                for entry in entries:
                    # MLflow returns paths relative to the queried DBFS folder's parent,
                    # so use the basename and retain our own traversal prefix.
                    relative = (
                        f"{prefix}/{Path(entry.path).name}" if prefix else Path(entry.path).name
                    )
                    if entry.is_dir:
                        pending.append(relative)
                    else:
                        result.append(f"logged_model/{relative}")
                if len(result) + len(pending) > 1000:
                    raise ValueError("artifact inventory exceeds the safety limit")
        return sorted(result)


class ArtifactSource(Protocol):
    @property
    def trust_level(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    def path(self, artifact_name: str) -> Path: ...


class LocalFixtureSource:
    """Explicit local test artifacts. Its output can never be marked deployable."""

    trust_level = "test_only"

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)

    @property
    def source_id(self) -> str:
        return f"local-fixture:{self.root}"

    def path(self, artifact_name: str) -> Path:
        relative = Path(artifact_name)
        if (
            not artifact_name
            or relative.is_absolute()
            or "\\" in artifact_name
            or ":" in artifact_name
            or any(part in (".", "..") for part in relative.parts)
        ):
            raise ValueError("invalid artifact path")
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("artifact source traverses a symlink")
        resolved = current.resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("artifact source is outside its trusted root or is not a file")
        return resolved
