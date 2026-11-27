"""Targeted cleanup of the DBX-00 POC resources ONLY. Dry run by default.

    python -m mlops.databricks_poc.cleanup                 # list what would be deleted
    python -m mlops.databricks_poc.cleanup --endpoint-only # delete only the serving endpoint
    python -m mlops.databricks_poc.cleanup --yes           # delete everything listed below

Deleted (in this order): serving endpoint argos-quality-poc, jobs argos-poc-*, registered
model workspace.argos_poc.quality_demo (all versions), experiment /Shared/ARGOS-POC/quality-demo,
schema workspace.argos_poc (CASCADE: tables + Volume images + code), workspace folder
/Shared/ARGOS-POC (launcher and diagnostic notebooks). The SQL warehouse is only
STOPPED (it existed before the POC). Foundation-model endpoints are never touched.
"""

from __future__ import annotations

import argparse
import sys

from mlops.databricks_poc.common import (
    CATALOG,
    ENDPOINT,
    EXPERIMENT,
    JOB_NAME,
    MODEL,
    MONITOR_JOB_NAME,
    SCHEMA,
    WORKSPACE_DIR,
    workspace_client,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="really delete (otherwise dry run)")
    parser.add_argument(
        "--endpoint-only", action="store_true", help="delete only the serving endpoint"
    )
    args = parser.parse_args(argv)
    w = workspace_client()
    plan = [("serving endpoint", ENDPOINT, lambda: w.serving_endpoints.delete(ENDPOINT))]
    if not args.endpoint_only:
        for name in (JOB_NAME, MONITOR_JOB_NAME):
            for job in w.jobs.list(name=name):
                plan.append(
                    ("job", f"{name} ({job.job_id})", lambda j=job.job_id: w.jobs.delete(j))
                )
        plan.append(("registered model (versions first)", MODEL, lambda: _delete_model(w)))
        experiment = (
            w.experiments.get_by_name(EXPERIMENT).experiment
            if _exists(lambda: w.experiments.get_by_name(EXPERIMENT))
            else None
        )
        if experiment:
            plan.append(
                (
                    "experiment",
                    f"{EXPERIMENT} ({experiment.experiment_id})",
                    lambda: w.experiments.delete_experiment(experiment.experiment_id),
                )
            )
        plan.append(
            (
                "schema (cascade)",
                f"{CATALOG}.{SCHEMA}",
                lambda: w.schemas.delete(f"{CATALOG}.{SCHEMA}", force=True),
            )
        )
        plan.append(
            (
                "workspace folder",
                WORKSPACE_DIR,
                lambda: w.workspace.delete(WORKSPACE_DIR, recursive=True),
            )
        )
    for kind, name, action in plan:
        if not args.yes and not args.endpoint_only:
            print(f"[dry run] would delete {kind}: {name}")
            continue
        try:
            action()
            print(f"deleted {kind}: {name}")
        except Exception as exc:  # noqa: BLE001 - continue with the others, report everything
            print(f"could not delete {kind} {name}: {type(exc).__name__}: {str(exc)[:150]}")
    return 0


def _delete_model(w) -> None:
    """Unity Catalog refuses to delete a model that still has versions."""
    for version in w.model_versions.list(MODEL):
        w.model_versions.delete(MODEL, version.version)
    w.registered_models.delete(MODEL)


def _exists(call) -> bool:
    try:
        call()
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
