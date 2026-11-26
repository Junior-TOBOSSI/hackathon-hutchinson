"""ARGOS Databricks connector: one façade over Unity Catalog, MLflow (tracking + UC registry),
Lakeflow Jobs, Model Serving and the monitoring Delta table.

- Credentials stay in the CLI OAuth profile of this process: nothing secret is returned.
- MLflow / UC remain the source of truth: no copy in another database.
- Read models are the MLOPS-01 ones (``mlops.connectors.mlflow_client``) and the ARGOS
  contracts (``ModelRef``, ``MonitoringMetrics``, ``DriftMeasure``).
- Three notions are kept apart for every version: APPROVED (version tag ``argos_approval``),
  ALIAS (``champion`` / ``challenger`` in UC) and SERVED (what an endpoint really runs).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from mlops.connectors.mlflow_client import (
    ExperimentInfo,
    MetricPoint,
    ModelVersionInfo,
    RunSummary,
    _experiment,
    _run,
    _ts,
)
from mlops.databricks.settings import DatabricksSettings, ManagedModel
from visionhub.contracts import UseCase
from visionhub.integration.mlops import DriftMeasure, ModelRef, MonitoringMetrics

T = TypeVar("T")
APPROVAL_TAG = "argos_approval"
PROMOTABLE_ALIASES = ("champion", "challenger")


# --------------------------------------------------------------------------- errors


class DatabricksConnectorError(Exception):
    status_code = 502


class DatabricksUnavailableError(DatabricksConnectorError):
    status_code = 503


class ResourceNotFoundError(DatabricksConnectorError):
    status_code = 404


class ForbiddenOperationError(DatabricksConnectorError):
    status_code = 403


class ConflictError(DatabricksConnectorError):
    status_code = 409


# --------------------------------------------------------------------------- read models


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class ConnectionStatus(_Model):
    ok: bool
    host: str
    user_active: bool
    profile: str


class SchemaInfo(_Model):
    catalog: str
    name: str
    full_name: str
    comment: str | None


class JobRunInfo(_Model):
    run_id: int
    job_id: int | None
    life_cycle_state: str | None
    result_state: str | None
    state_message: str | None
    start_time: datetime | None
    end_time: datetime | None
    duration_s: float | None
    run_page_url: str | None


class JobInfo(_Model):
    job_id: int
    name: str
    scheduled: bool
    triggerable: bool
    last_run: JobRunInfo | None


class ServedEntity(_Model):
    name: str | None
    model: str | None
    version: str | None
    workload_size: str | None
    scale_to_zero: bool | None
    deployment: str | None


class EndpointInfo(_Model):
    name: str
    ready: str | None
    config_update: str | None
    served: list[ServedEntity]
    pending_versions: list[str]


class VersionStatus(_Model):
    version: ModelVersionInfo
    approved: bool
    aliases: list[str]
    served_by: list[str]


class ModelStatus(_Model):
    """APPROVED, ALIAS and SERVED side by side, for one managed model."""

    model_id: str
    uc_name: str
    aliases: dict[str, str]
    served: dict[str, str | None]  # endpoint -> served version
    versions: list[VersionStatus]


class MonitoringReport(_Model):
    available: bool
    reason: str | None = None
    table: str
    metrics: MonitoringMetrics | None = None
    accuracies: dict[str, float | None] = {}
    read_at: datetime | None = None


# --------------------------------------------------------------------------- connector


class DatabricksConnector:
    def __init__(
        self, settings: DatabricksSettings | None = None, workspace=None, mlflow_client=None
    ) -> None:
        self.settings = settings or DatabricksSettings.from_env()
        self.settings.apply_process_environment()
        if workspace is None:
            from databricks.sdk import WorkspaceClient

            workspace = WorkspaceClient(profile=self.settings.profile)
        if mlflow_client is None:
            from mlflow import MlflowClient

            mlflow_client = MlflowClient(tracking_uri="databricks", registry_uri="databricks-uc")
        self.w = workspace
        self.mlflow = mlflow_client
        self._cache: dict[str, tuple[float, Any]] = {}

    # ------------------------------------------------------------------ plumbing

    def _call(self, fn: Callable[[], T], what: str = "resource") -> T:
        try:
            return fn()
        except DatabricksConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated into explicit errors below
            name, message = type(exc).__name__, str(exc)
            if (
                name in ("NotFound", "ResourceDoesNotExist")
                or "RESOURCE_DOES_NOT_EXIST" in message
                or "does not exist" in message.lower()
            ):
                raise ResourceNotFoundError(f"{what} not found") from exc
            if name in ("PermissionDenied", "Unauthenticated") or "PERMISSION_DENIED" in message:
                raise ForbiddenOperationError(f"permission denied on {what}") from exc
            if any(
                k in message
                for k in ("Max retries", "Connection", "timed out", "Temporarily unavailable")
            ):
                raise DatabricksUnavailableError("Databricks unreachable") from exc
            raise DatabricksConnectorError(f"{name}: {message[:300]}") from exc

    def managed(self, model_id: str) -> ManagedModel:
        model = self.settings.model(model_id)
        if model is None:
            raise ResourceNotFoundError(f"unknown model id {model_id!r}")
        return model

    # ------------------------------------------------------------------ workspace / UC

    def ping(self) -> ConnectionStatus:
        me = self._call(lambda: self.w.current_user.me(), "current user")
        return ConnectionStatus(
            ok=True,
            host=self.w.config.host,
            user_active=bool(me.active),
            profile=self.settings.profile,
        )

    def list_catalogs(self) -> list[str]:
        return self._call(lambda: [c.name for c in self.w.catalogs.list()], "catalogs")

    def list_schemas(self, catalog: str | None = None) -> list[SchemaInfo]:
        catalog = catalog or self.settings.catalog
        return self._call(
            lambda: [
                SchemaInfo(catalog=catalog, name=s.name, full_name=s.full_name, comment=s.comment)
                for s in self.w.schemas.list(catalog_name=catalog)
            ],
            f"schemas of {catalog}",
        )

    # ------------------------------------------------------------------ MLflow tracking

    def list_experiments(self) -> list[ExperimentInfo]:
        out = []
        for path in self.settings.experiments:
            experiment = self._call(
                lambda p=path: self.mlflow.get_experiment_by_name(p), f"experiment {path}"
            )
            if experiment is not None:
                out.append(_experiment(experiment))
        return out

    def get_experiment(self, experiment_id: str) -> ExperimentInfo:
        return _experiment(
            self._call(
                lambda: self.mlflow.get_experiment(experiment_id), f"experiment {experiment_id}"
            )
        )

    def list_runs(self, experiment_id: str, max_results: int = 50) -> list[RunSummary]:
        runs = self._call(
            lambda: self.mlflow.search_runs(
                [experiment_id], max_results=max_results, order_by=["attributes.start_time DESC"]
            ),
            f"runs of {experiment_id}",
        )
        return [_run(r) for r in runs]

    def get_run(self, run_id: str) -> RunSummary:
        return _run(self._call(lambda: self.mlflow.get_run(run_id), f"run {run_id}"))

    def metric_history(self, run_id: str, key: str) -> list[MetricPoint]:
        self.get_run(run_id)
        history = self._call(lambda: self.mlflow.get_metric_history(run_id, key), f"metric {key}")
        # Databricks may return the same point twice: keep one per (step, timestamp, value).
        unique = {(m.step, m.timestamp, m.value): m for m in history}.values()
        return sorted(
            (
                MetricPoint(key=m.key, value=m.value, step=m.step, timestamp=_ts(m.timestamp))
                for m in unique
            ),
            key=lambda p: (p.step, p.timestamp),
        )

    def compare_runs(self, run_ids: list[str]) -> dict[str, Any]:
        """Metrics and params of several runs side by side (keys = union of all runs)."""
        runs = [self.get_run(r) for r in run_ids]
        metric_keys = sorted({k for r in runs for k in r.metrics})
        param_keys = sorted({k for r in runs for k in r.params})
        return {
            "runs": [{"run_id": r.run_id, "run_name": r.run_name} for r in runs],
            "metrics": {k: {r.run_id: r.metrics.get(k) for r in runs} for k in metric_keys},
            "params": {k: {r.run_id: r.params.get(k) for r in runs} for k in param_keys},
        }

    # ------------------------------------------------------------------ UC registry

    def model_versions(self, model_id: str) -> list[ModelVersionInfo]:
        managed = self.managed(model_id)
        registered = self._call(
            lambda: self.mlflow.get_registered_model(managed.uc_name), managed.uc_name
        )
        aliases_by_version: dict[str, list[str]] = {}
        for alias, version in (registered.aliases or {}).items():
            aliases_by_version.setdefault(str(version), []).append(alias)
        numbers = sorted(
            int(v.version)
            for v in self._call(
                lambda: self.mlflow.search_model_versions(f"name = '{managed.uc_name}'"),
                managed.uc_name,
            )
        )
        out = []
        for number in numbers:
            # UC search results carry no tags: read each version.
            v = self._call(
                lambda n=number: self.mlflow.get_model_version(managed.uc_name, str(n)),
                f"version {number}",
            )
            out.append(
                ModelVersionInfo(
                    name=v.name,
                    version=str(v.version),
                    aliases=sorted(aliases_by_version.get(str(v.version), [])),
                    run_id=v.run_id or None,
                    model_id=getattr(v, "model_id", None) or None,
                    source=v.source or "",
                    status=str(v.status),
                    tags=dict(v.tags or {}),
                    created_at=_ts(v.creation_timestamp),
                )
            )
        return out

    def resolve_alias(self, model_id: str, alias: str) -> ModelRef:
        managed = self.managed(model_id)
        version = self._call(
            lambda: self.mlflow.get_model_version_by_alias(managed.uc_name, alias), f"alias {alias}"
        )
        return ModelRef(
            registered_model=managed.uc_name,
            version=str(version.version),
            alias=alias,
            mlflow_run_id=version.run_id or None,
        )

    def model_status(self, model_id: str) -> ModelStatus:
        managed = self.managed(model_id)
        versions = self.model_versions(model_id)
        served: dict[str, str | None] = {}
        if managed.endpoint:
            endpoint = self.get_endpoint(managed.endpoint)
            served[endpoint.name] = next(
                (s.version for s in endpoint.served if s.model == managed.uc_name), None
            )
        aliases = {alias: v.version for v in versions for alias in v.aliases}
        return ModelStatus(
            model_id=model_id,
            uc_name=managed.uc_name,
            aliases=aliases,
            served=served,
            versions=[
                VersionStatus(
                    version=v,
                    approved=v.tags.get(APPROVAL_TAG) == "approved",
                    aliases=v.aliases,
                    served_by=[e for e, sv in served.items() if sv == v.version],
                )
                for v in versions
            ],
        )

    def approve_version(
        self, model_id: str, version: str, approved_by_role: str = "ai_leader"
    ) -> VersionStatus:
        """Record a HUMAN approval on a version (tag). Does not move any alias, serves nothing."""
        managed = self.managed(model_id)
        self._call(
            lambda: self.mlflow.get_model_version(managed.uc_name, version), f"version {version}"
        )
        self._call(
            lambda: self.mlflow.set_model_version_tag(
                managed.uc_name, version, APPROVAL_TAG, "approved"
            ),
            "tag",
        )
        self._call(
            lambda: self.mlflow.set_model_version_tag(
                managed.uc_name, version, "argos_approved_by", approved_by_role
            ),
            "tag",
        )
        return next(v for v in self.model_status(model_id).versions if v.version.version == version)

    def set_alias(self, model_id: str, alias: str, version: str) -> ModelStatus:
        """Registry promotion (alias). The served version is NOT changed by this call."""
        if alias not in PROMOTABLE_ALIASES:
            raise ForbiddenOperationError(f"alias must be one of {PROMOTABLE_ALIASES}")
        managed = self.managed(model_id)
        self._call(
            lambda: self.mlflow.get_model_version(managed.uc_name, version), f"version {version}"
        )
        self._call(
            lambda: self.mlflow.set_registered_model_alias(managed.uc_name, alias, version), "alias"
        )
        return self.model_status(model_id)

    # ------------------------------------------------------------------ jobs

    def _job_run(self, run) -> JobRunInfo:
        state = run.state
        return JobRunInfo(
            run_id=run.run_id,
            job_id=run.job_id,
            life_cycle_state=state.life_cycle_state.value
            if state and state.life_cycle_state
            else None,
            result_state=state.result_state.value if state and state.result_state else None,
            state_message=state.state_message if state else None,
            start_time=_ts(run.start_time),
            end_time=_ts(run.end_time),
            duration_s=round((run.end_time - run.start_time) / 1000, 1)
            if run.end_time and run.start_time
            else None,
            run_page_url=run.run_page_url,
        )

    def list_jobs(self) -> list[JobInfo]:
        out = []
        for job in self._call(lambda: list(self.w.jobs.list()), "jobs"):
            settings = job.settings
            last = next(
                iter(
                    self._call(
                        lambda j=job.job_id: list(self.w.jobs.list_runs(job_id=j, limit=1)), "runs"
                    )
                ),
                None,
            )
            out.append(
                JobInfo(
                    job_id=job.job_id,
                    name=settings.name,
                    scheduled=bool(settings.schedule or settings.trigger or settings.continuous),
                    triggerable=settings.name in self.settings.triggerable_jobs,
                    last_run=self._job_run(last) if last else None,
                )
            )
        return out

    def job_runs(self, job_id: int, limit: int = 10) -> list[JobRunInfo]:
        return [
            self._job_run(r)
            for r in self._call(
                lambda: list(self.w.jobs.list_runs(job_id=job_id, limit=limit)), f"job {job_id}"
            )
        ]

    def get_job_run(self, run_id: int) -> JobRunInfo:
        return self._job_run(self._call(lambda: self.w.jobs.get_run(run_id), f"job run {run_id}"))

    def trigger_job(self, job_name: str) -> JobRunInfo:
        """Run an EXISTING allow-listed job; refused if a run is already active (cost guard)."""
        if job_name not in self.settings.triggerable_jobs:
            raise ForbiddenOperationError(f"job {job_name!r} is not triggerable from ARGOS")
        job = next(
            iter(self._call(lambda: list(self.w.jobs.list(name=job_name)), f"job {job_name}")), None
        )
        if job is None:
            raise ResourceNotFoundError(f"job {job_name!r} not found")
        if list(
            self._call(
                lambda: list(self.w.jobs.list_runs(job_id=job.job_id, active_only=True)), "runs"
            )
        ):
            raise ConflictError(f"job {job_name!r} already has an active run")
        run_id = self._call(lambda: self.w.jobs.run_now(job.job_id).run_id, f"job {job_name}")
        return self.get_job_run(run_id)

    # ------------------------------------------------------------------ serving

    def _endpoint(self, e) -> EndpointInfo:
        entities = (e.config.served_entities if e.config else None) or []
        pending = (e.pending_config.served_entities if e.pending_config else None) or []
        return EndpointInfo(
            name=e.name,
            ready=e.state.ready.value if e.state and e.state.ready else None,
            config_update=e.state.config_update.value
            if e.state and e.state.config_update
            else None,
            served=[
                ServedEntity(
                    name=s.name,
                    model=s.entity_name,
                    version=s.entity_version,
                    workload_size=s.workload_size,
                    scale_to_zero=s.scale_to_zero_enabled,
                    deployment=s.state.deployment.value if s.state and s.state.deployment else None,
                )
                for s in entities
            ],
            pending_versions=[s.entity_version for s in pending if s.entity_version],
        )

    def list_endpoints(self, include_foundation: bool = False) -> list[EndpointInfo]:
        endpoints = self._call(lambda: list(self.w.serving_endpoints.list()), "serving endpoints")
        return [
            self._endpoint(self._call(lambda n=e.name: self.w.serving_endpoints.get(n), e.name))
            for e in endpoints
            if include_foundation or not (e.name or "").startswith("databricks-")
        ]

    def get_endpoint(self, name: str) -> EndpointInfo:
        return self._endpoint(
            self._call(lambda: self.w.serving_endpoints.get(name), f"endpoint {name}")
        )

    # ------------------------------------------------------------------ monitoring

    def _warehouse_id(self) -> str:
        if self.settings.warehouse_id:
            return self.settings.warehouse_id
        warehouse = next(
            iter(self._call(lambda: list(self.w.warehouses.list()), "warehouses")), None
        )
        if warehouse is None:
            raise ResourceNotFoundError("no SQL warehouse")
        return warehouse.id

    def _sql(self, statement: str) -> list[list]:
        wid = self._warehouse_id()
        state = self._call(lambda: self.w.warehouses.get(wid).state.value, "warehouse")
        if state != "RUNNING" and not self.settings.warehouse_autostart:
            raise ConflictError(
                f"SQL warehouse is {state} and autostart is disabled (no cost incurred)"
            )
        response = self._call(
            lambda: self.w.statement_execution.execute_statement(
                statement=statement, warehouse_id=wid, wait_timeout="50s"
            ),
            "SQL statement",
        )
        deadline = time.time() + 120
        while response.status.state.value in ("PENDING", "RUNNING") and time.time() < deadline:
            time.sleep(2)
            response = self._call(
                lambda sid=response.statement_id: self.w.statement_execution.get_statement(sid),
                "SQL",
            )
        if response.status.state.value != "SUCCEEDED":
            raise DatabricksConnectorError(
                f"SQL {response.status.state.value}: {response.status.error}"
            )
        return (response.result.data_array or []) if response.result else []

    def monitoring(self, model_id: str, refresh: bool = False) -> MonitoringReport:
        """Latest drift report of a model, as the ARGOS ``MonitoringMetrics`` contract.

        Cached ``cache_seconds`` so that a polling UI never multiplies SQL queries; a
        stopped warehouse gives ``available=False`` (never started unless configured).
        """
        key = f"monitoring:{model_id}"
        cached = self._cache.get(key)
        if cached and not refresh and time.time() - cached[0] < self.settings.cache_seconds:
            return cached[1]
        managed = self.managed(model_id)
        table = self.settings.monitoring_table
        try:
            rows = self._sql(
                "SELECT feature, method, value, threshold, alert, n_reference, n_current, "
                f"computed_at FROM {table}"
            )
        except ConflictError as exc:
            report = MonitoringReport(available=False, reason=str(exc), table=table)
            self._cache[key] = (time.time(), report)
            return report
        drift, accuracies, n, computed = [], {}, 0, []
        for feature, method, value, threshold, alert, n_ref, n_cur, at in rows:
            computed.append(at)
            if method == "labelled_accuracy":
                accuracies[feature] = float(value) if value is not None else None
                continue
            drift.append(
                DriftMeasure(
                    feature=feature,
                    method=method,
                    value=float(value),
                    threshold=float(threshold),
                    alert=str(alert).lower() == "true",
                )
            )
            n = max(n, int(n_ref or 0) + int(n_cur or 0))
        status = self.model_status(model_id)
        version = (
            next(iter(v for v in status.served.values() if v), None)
            or status.aliases.get("champion")
            or "1"
        )
        moment = datetime.fromisoformat(max(computed)) if computed else datetime.now(UTC)
        metrics = MonitoringMetrics(
            use_case=UseCase(managed.argos_use_case),
            model=ModelRef(registered_model=managed.uc_name, version=version),
            window_start=moment,
            window_end=moment,
            n_inferences=n,
            drift=drift,
        )
        report = MonitoringReport(
            available=True,
            table=table,
            metrics=metrics,
            accuracies=accuracies,
            read_at=datetime.now(UTC),
        )
        self._cache[key] = (time.time(), report)
        return report
