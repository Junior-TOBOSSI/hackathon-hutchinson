"""Hybrid training: the ENGINE that trains is separate from the TRACKING that records.

Databricks is the main engine (``DatabricksJobBackend``: an existing Lakeflow job). Any
other engine (laptop, external GPU cluster) only has to log to MLflow Databricks with
``use_databricks_tracking()`` and register in Unity Catalog: the AI Leader then sees its
runs and versions exactly like Databricks ones. No scheduler and no automatic fallback
are implemented on purpose.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mlops.databricks.connector import DatabricksConnector, JobRunInfo


@runtime_checkable
class TrainingBackend(Protocol):
    """Starts a training of a managed model and reports its state."""

    name: str

    def submit(self, model_id: str) -> JobRunInfo: ...

    def status(self, run_id: int) -> JobRunInfo: ...


class DatabricksJobBackend:
    """Runs the EXISTING Lakeflow job declared for the model (``ManagedModel.training_job``)."""

    name = "databricks-jobs"

    def __init__(self, connector: DatabricksConnector) -> None:
        self.connector = connector

    def submit(self, model_id: str) -> JobRunInfo:
        managed = self.connector.managed(model_id)
        if not managed.training_job:
            from mlops.databricks.connector import ResourceNotFoundError

            raise ResourceNotFoundError(f"model {model_id!r} has no training job declared")
        return self.connector.trigger_job(managed.training_job)

    def status(self, run_id: int) -> JobRunInfo:
        return self.connector.get_job_run(run_id)


def use_databricks_tracking(experiment: str, profile: str = "ARGOS") -> None:
    """For an EXTERNAL training script: log runs to MLflow Databricks, register in UC.

    from mlops.databricks.training import use_databricks_tracking
    use_databricks_tracking("/Shared/ARGOS/quality")
    with mlflow.start_run(): ...  # params, metrics, mlflow.<flavor>.log_model(..., signature=...)
    mlflow.register_model(model_info.model_uri, "workspace.<schema>.<model>")
    """
    import mlflow

    from mlops.databricks.settings import DatabricksSettings

    DatabricksSettings(profile=profile).apply_process_environment()
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(experiment)
