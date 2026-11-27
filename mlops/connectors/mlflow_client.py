"""ARGOS MLflow connector: the only way ARGOS services talk to MLflow.

It wraps ``mlflow.MlflowClient`` (tracking + registry, over HTTP) and returns small,
JSON-friendly Pydantic read models, ready to be served by a future FastAPI layer to the
AI Leader frontend. The frontend never calls MLflow directly.

Design rules:
- MLflow is the source of truth: nothing is copied into another database.
- Only the REST API is used: no access to MLflow's SQLite file or artifact folder.
- MLflow errors are translated into the explicit errors of ``errors.py``.
- Model versions are exposed with the ARGOS contract ``ModelRef``.
- Registry WRITE operations are restricted to demonstration models (``DEMO_PREFIX``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import requests
from mlflow import MlflowClient
from mlflow.entities import ViewType
from mlflow.exceptions import MlflowException
from pydantic import BaseModel, ConfigDict

from mlops.config import DEMO_PREFIX, MlflowSettings
from mlops.connectors.errors import (
    AliasNotFoundError,
    ArtifactDownloadError,
    ExperimentNotFoundError,
    ForbiddenOperationError,
    MlflowConnectorError,
    ModelVersionNotFoundError,
    NotFoundError,
    RegisteredModelNotFoundError,
    RunNotFoundError,
    ServerUnavailableError,
)
from visionhub.integration.mlops import ModelRef

T = TypeVar("T")

LOGGED_MODEL_TAG = "argos.logged_model_id"

_CONNECTION_MARKERS = (
    "Max retries exceeded",
    "Connection refused",
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "timed out",
    "Failed to establish a new connection",
)


# --------------------------------------------------------------------------- read models


class _ReadModel(BaseModel):
    model_config = ConfigDict(frozen=True)


def _ts(millis: int | None) -> datetime | None:
    return datetime.fromtimestamp(millis / 1000, tz=UTC) if millis else None


class ServerStatus(_ReadModel):
    tracking_uri: str
    registry_uri: str
    healthy: bool
    version: str


class ExperimentInfo(_ReadModel):
    experiment_id: str
    name: str
    lifecycle_stage: str
    artifact_location: str
    tags: dict[str, str]
    created_at: datetime | None


class RunSummary(_ReadModel):
    run_id: str
    run_name: str | None
    experiment_id: str
    status: str
    start_time: datetime | None
    end_time: datetime | None
    artifact_uri: str
    params: dict[str, str]
    metrics: dict[str, float]
    tags: dict[str, str]


class MetricPoint(_ReadModel):
    key: str
    value: float
    step: int
    timestamp: datetime | None


class ArtifactInfo(_ReadModel):
    path: str
    is_dir: bool
    file_size: int | None


class ModelVersionInfo(_ReadModel):
    name: str
    version: str
    aliases: list[str]
    run_id: str | None
    model_id: str | None
    source: str
    status: str
    tags: dict[str, str]
    created_at: datetime | None

    @property
    def uri(self) -> str:
        return f"models:/{self.name}/{self.version}"


class RegisteredModelInfo(_ReadModel):
    name: str
    description: str | None
    tags: dict[str, str]
    aliases: dict[str, str]  # alias -> version
    latest_version: str | None
    created_at: datetime | None


# --------------------------------------------------------------------------- connector


class ArgosMlflowConnector:
    def __init__(
        self, settings: MlflowSettings | None = None, client: MlflowClient | None = None
    ) -> None:
        self.settings = settings or MlflowSettings.from_env()
        self.settings.apply_http_policy()
        self.client = client or MlflowClient(
            tracking_uri=self.settings.tracking_uri, registry_uri=self.settings.registry_uri
        )

    # ------------------------------------------------------------------ plumbing

    def _call(self, fn: Callable[[], T], not_found: NotFoundError | None = None) -> T:
        """Run an MLflow call and translate its errors."""
        try:
            return fn()
        except MlflowException as exc:
            message = str(exc)
            if exc.error_code == "RESOURCE_DOES_NOT_EXIST" and not_found is not None:
                raise not_found from exc
            if any(marker in message for marker in _CONNECTION_MARKERS):
                raise ServerUnavailableError(
                    f"MLflow server unreachable at {self.settings.tracking_uri}"
                ) from exc
            raise MlflowConnectorError(message) from exc
        except requests.RequestException as exc:
            raise ServerUnavailableError(
                f"MLflow server unreachable at {self.settings.tracking_uri}"
            ) from exc

    def ping(self) -> ServerStatus:
        """Check that the tracking server answers (``/health`` and ``/version``)."""
        base = self.settings.tracking_uri.rstrip("/")
        timeout = self.settings.request_timeout_s
        try:
            health = requests.get(f"{base}/health", timeout=timeout)
            version = requests.get(f"{base}/version", timeout=timeout)
        except requests.RequestException as exc:
            raise ServerUnavailableError(f"MLflow server unreachable at {base}") from exc
        if health.status_code != 200:
            raise ServerUnavailableError(f"MLflow /health answered HTTP {health.status_code}")
        return ServerStatus(
            tracking_uri=self.settings.tracking_uri,
            registry_uri=self.settings.registry_uri,
            healthy=health.text.strip() == "OK",
            version=version.text.strip() if version.ok else "unknown",
        )

    # ------------------------------------------------------------------ experiments

    def list_experiments(self, include_deleted: bool = False) -> list[ExperimentInfo]:
        view = ViewType.ALL if include_deleted else ViewType.ACTIVE_ONLY
        experiments = self._call(lambda: self.client.search_experiments(view_type=view))
        return [_experiment(e) for e in experiments]

    def get_experiment(self, experiment_id_or_name: str) -> ExperimentInfo:
        missing = ExperimentNotFoundError(f"unknown experiment {experiment_id_or_name!r}")
        experiment = self._call(lambda: self.client.get_experiment_by_name(experiment_id_or_name))
        if experiment is None:
            if not experiment_id_or_name.isdigit():
                raise missing
            experiment = self._call(
                lambda: self.client.get_experiment(experiment_id_or_name), missing
            )
        return _experiment(experiment)

    # ------------------------------------------------------------------ runs

    def list_runs(
        self, experiment_id_or_name: str, max_results: int = 100, order_by: list[str] | None = None
    ) -> list[RunSummary]:
        experiment = self.get_experiment(experiment_id_or_name)
        runs = self._call(
            lambda: self.client.search_runs(
                [experiment.experiment_id],
                max_results=max_results,
                order_by=order_by or ["attributes.start_time DESC"],
            )
        )
        return [_run(r) for r in runs]

    def get_run(self, run_id: str) -> RunSummary:
        return _run(
            self._call(
                lambda: self.client.get_run(run_id), RunNotFoundError(f"unknown run {run_id!r}")
            )
        )

    def get_run_params(self, run_id: str) -> dict[str, str]:
        return self.get_run(run_id).params

    def get_run_metrics(self, run_id: str) -> dict[str, float]:
        """Last value of each metric of the run."""
        return self.get_run(run_id).metrics

    def get_metric_history(self, run_id: str, key: str) -> list[MetricPoint]:
        """Every logged value of one metric, ordered by step (MLflow returns [] for an
        unknown run, so the run is checked first)."""
        self.get_run(run_id)
        history = self._call(lambda: self.client.get_metric_history(run_id, key))
        points = [
            MetricPoint(key=m.key, value=m.value, step=m.step, timestamp=_ts(m.timestamp))
            for m in history
        ]
        return sorted(
            points, key=lambda p: (p.step, p.timestamp or datetime.min.replace(tzinfo=UTC))
        )

    # ------------------------------------------------------------------ artifacts

    def list_artifacts(self, run_id: str, path: str | None = None) -> list[ArtifactInfo]:
        missing = RunNotFoundError(f"unknown run {run_id!r}")
        try:
            files = self._call(lambda: self.client.list_artifacts(run_id, path), missing)
        except (NotFoundError, ServerUnavailableError):
            raise
        except MlflowConnectorError as exc:
            raise ArtifactDownloadError(f"cannot list artifacts of run {run_id}: {exc}") from exc
        return [ArtifactInfo(path=f.path, is_dir=f.is_dir, file_size=f.file_size) for f in files]

    def download_artifact(
        self, run_id: str, path: str, destination: Path | str | None = None
    ) -> Path:
        """Download a run artifact (file or folder) into an AUTHORIZED folder.

        ``destination`` must be inside ``settings.download_dir`` (default: a folder per run).
        """
        root = self.settings.download_dir.resolve()
        target = Path(destination).resolve() if destination else root / run_id
        if not target.is_relative_to(root):
            raise ArtifactDownloadError(f"destination {target} is outside {root}")
        target.mkdir(parents=True, exist_ok=True)
        self.get_run(run_id)
        try:
            local = self._call(
                lambda: self.client.download_artifacts(run_id, path, dst_path=str(target))
            )
        except ServerUnavailableError:
            raise
        except MlflowConnectorError as exc:
            raise ArtifactDownloadError(f"cannot download {path!r} of run {run_id}: {exc}") from exc
        return Path(local)

    # ------------------------------------------------------------------ registry (read)

    def list_registered_models(self) -> list[RegisteredModelInfo]:
        models = self._call(lambda: self.client.search_registered_models())
        return [_registered_model(m) for m in models]

    def get_registered_model(self, name: str) -> RegisteredModelInfo:
        return _registered_model(
            self._call(
                lambda: self.client.get_registered_model(name),
                RegisteredModelNotFoundError(f"unknown registered model {name!r}"),
            )
        )

    def list_model_versions(self, name: str) -> list[ModelVersionInfo]:
        model = self.get_registered_model(name)
        escaped = name.replace("'", "\\'")
        versions = self._call(lambda: self.client.search_model_versions(f"name = '{escaped}'"))
        # search_model_versions does not return aliases: take them from the registered model.
        aliases_by_version: dict[str, list[str]] = {}
        for alias, version in model.aliases.items():
            aliases_by_version.setdefault(version, []).append(alias)
        infos = [
            _version(v).model_copy(
                update={"aliases": sorted(aliases_by_version.get(str(v.version), []))}
            )
            for v in versions
        ]
        return sorted(infos, key=lambda v: int(v.version))

    def get_model_version(self, name: str, version: str | int) -> ModelVersionInfo:
        self.get_registered_model(name)
        return _version(
            self._call(
                lambda: self.client.get_model_version(name, str(version)),
                ModelVersionNotFoundError(f"unknown version {version} of model {name!r}"),
            )
        )

    def resolve_alias(self, name: str, alias: str) -> ModelVersionInfo:
        """``models:/<name>@<alias>`` -> the version the alias points to RIGHT NOW."""
        model = self.get_registered_model(name)
        if alias not in model.aliases:
            raise AliasNotFoundError(f"alias {alias!r} is not set on model {name!r}")
        return _version(
            self._call(
                lambda: self.client.get_model_version_by_alias(name, alias),
                AliasNotFoundError(f"alias {alias!r} is not set on model {name!r}"),
            )
        )

    def resolve(self, model_uri: str) -> ModelVersionInfo:
        """Resolve ``models:/<name>/<version>`` or ``models:/<name>@<alias>``."""
        if not model_uri.startswith("models:/"):
            raise ValueError(f"not a registry model URI: {model_uri!r}")
        reference = model_uri.removeprefix("models:/")
        if "@" in reference:
            name, alias = reference.rsplit("@", 1)
            return self.resolve_alias(name, alias)
        name, _, version = reference.rpartition("/")
        if not name or not version.isdigit():
            raise ValueError(
                f"expected models:/<name>/<version> or models:/<name>@<alias>: {model_uri!r}"
            )
        return self.get_model_version(name, version)

    @staticmethod
    def to_model_ref(version: ModelVersionInfo, alias: str | None = None) -> ModelRef:
        """Map an MLflow model version to the ARGOS contract ``ModelRef``."""
        return ModelRef(
            registered_model=version.name,
            version=version.version,
            alias=alias,
            mlflow_run_id=version.run_id,
        )

    # ------------------------------------------------------------------ registry (demo writes)

    @staticmethod
    def _check_demo(name: str) -> None:
        if not name.startswith(DEMO_PREFIX):
            raise ForbiddenOperationError(
                f"registry writes are limited to demonstration models ({DEMO_PREFIX}*): {name!r}"
            )

    def register_demo_model(
        self,
        name: str,
        model_id: str,
        tags: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> ModelVersionInfo:
        """Create (if needed) a demo registered model and a new version from a Logged Model.

        The version keeps the link to its training: ``run_id`` and ``model_id``.
        """
        self._check_demo(name)
        logged = self._call(
            lambda: self.client.get_logged_model(model_id),
            NotFoundError(f"unknown logged model {model_id!r}"),
        )
        try:
            self.get_registered_model(name)
        except RegisteredModelNotFoundError:
            self._call(
                lambda: self.client.create_registered_model(
                    name,
                    tags={"synthetic": "true", "argos.workstream": "mlops"},
                    description=description,
                )
            )
        version = self._call(
            lambda: self.client.create_model_version(
                name=name,
                source=logged.artifact_location,
                run_id=logged.source_run_id,
                model_id=model_id,
                # The OSS registry does not return model_id when reading a version back:
                # keep the Logged Model link explicitly.
                tags={"synthetic": "true", LOGGED_MODEL_TAG: model_id, **(tags or {})},
            )
        )
        return _version(version)

    def set_demo_alias(self, name: str, alias: str, version: str | int) -> ModelVersionInfo:
        """Point an alias of a demonstration model to a version (moves it if it exists).

        This is a REGISTRY promotion only: nothing is deployed on any Edge station.
        """
        self._check_demo(name)
        self.get_model_version(name, version)
        self._call(lambda: self.client.set_registered_model_alias(name, alias, str(version)))
        return self.resolve_alias(name, alias)


# --------------------------------------------------------------------------- mappers


def _experiment(e: Any) -> ExperimentInfo:
    return ExperimentInfo(
        experiment_id=e.experiment_id,
        name=e.name,
        lifecycle_stage=e.lifecycle_stage,
        artifact_location=e.artifact_location,
        tags=dict(e.tags),
        created_at=_ts(getattr(e, "creation_time", None)),
    )


def _run(r: Any) -> RunSummary:
    return RunSummary(
        run_id=r.info.run_id,
        run_name=r.info.run_name,
        experiment_id=r.info.experiment_id,
        status=r.info.status,
        start_time=_ts(r.info.start_time),
        end_time=_ts(r.info.end_time),
        artifact_uri=r.info.artifact_uri,
        params=dict(r.data.params),
        metrics=dict(r.data.metrics),
        tags={k: v for k, v in r.data.tags.items() if not k.startswith("mlflow.log-model")},
    )


def _version(v: Any) -> ModelVersionInfo:
    return ModelVersionInfo(
        name=v.name,
        version=str(v.version),
        aliases=list(getattr(v, "aliases", []) or []),
        run_id=v.run_id or None,
        model_id=getattr(v, "model_id", None) or dict(v.tags).get(LOGGED_MODEL_TAG),
        source=v.source,
        status=v.status,
        tags=dict(v.tags),
        created_at=_ts(v.creation_timestamp),
    )


def _registered_model(m: Any) -> RegisteredModelInfo:
    latest = [str(v.version) for v in (m.latest_versions or [])]
    return RegisteredModelInfo(
        name=m.name,
        description=m.description or None,
        tags=dict(m.tags),
        aliases={alias: str(version) for alias, version in (m.aliases or {}).items()},
        latest_version=max(latest, key=int) if latest else None,
        created_at=_ts(m.creation_timestamp),
    )
