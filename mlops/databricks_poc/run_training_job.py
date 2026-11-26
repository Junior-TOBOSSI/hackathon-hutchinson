"""DBX-00C: upload the training code, create/update the Lakeflow Job and run it from the PC.

    python -m mlops.databricks_poc.run_training_job

- code uploaded to the Unity Catalog Volume (/Volumes/.../images/code) and executed by the
  launcher NOTEBOOK /Shared/ARGOS-POC/run_volume_script. Diagnosed restrictions of this
  trial workspace (see README): serverless compute cannot read Workspace files (403 SSE-C)
  and spark_python_task refuses a Volume path; notebooks and Volumes both work;
- ONE job ``argos-poc-quality-training``: serverless CPU, no schedule, max 1 concurrent run,
  task timeout 40 min, no retry;
- run_now, then polling of the run state (bounded), output logs and summary retrieval.
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

from databricks.sdk.service import compute, jobs, workspace

from mlops.databricks_poc.common import (
    CATALOG,
    DATASET_DIR,
    EXPERIMENT,
    JOB_NAME,
    MODEL,
    SCHEMA,
    VOLUME_PATH,
    WORKSPACE_DIR,
    save_result,
    workspace_client,
)

CODE_DIR = f"{VOLUME_PATH}/code"
LAUNCHER = f"{WORKSPACE_DIR}/run_volume_script"
REMOTE_SOURCES = Path(__file__).parent / "remote"
DEPENDENCIES = [
    "mlflow==3.18.0",
    "scikit-learn==1.9.1",
    "numpy==2.4.6",
    "pandas==3.1.1",
    "pillow==13.0.0",
    "matplotlib",
    "joblib",
]
MAX_WAIT_S = 45 * 60


def upload_code(w) -> list[str]:
    uploaded = []
    for source in sorted(REMOTE_SOURCES.glob("*.py")):
        target = f"{CODE_DIR}/{source.name}"
        with source.open("rb") as handle:
            w.files.upload(target, handle, overwrite=True)
        uploaded.append(target)
    launcher = (REMOTE_SOURCES / "run_volume_script.py").read_bytes()
    w.workspace.mkdirs(WORKSPACE_DIR)
    w.workspace.import_(
        LAUNCHER,
        content=base64.b64encode(launcher).decode(),
        format=workspace.ImportFormat.SOURCE,
        language=workspace.Language.PYTHON,
        overwrite=True,
    )
    uploaded.append(LAUNCHER)
    return uploaded


def job_settings(script: str) -> dict:
    return {
        "name": JOB_NAME,
        "description": "ARGOS DBX-00 POC - synthetic data only. Manual trigger, no schedule.",
        "max_concurrent_runs": 1,
        "timeout_seconds": 3600,
        "tags": {"argos": "dbx-00-poc", "synthetic": "true"},
        "environments": [
            jobs.JobEnvironment(
                environment_key="default",
                spec=compute.Environment(environment_version="3", dependencies=DEPENDENCIES),
            )
        ],
        "tasks": [
            jobs.Task(
                task_key="train_quality",
                environment_key="default",
                timeout_seconds=40 * 60,
                max_retries=0,
                notebook_task=jobs.NotebookTask(
                    notebook_path=LAUNCHER,
                    base_parameters={
                        "script": script,
                        "args": json.dumps(
                            [
                                "--code-dir",
                                CODE_DIR,
                                "--dataset-dir",
                                DATASET_DIR,
                                "--experiment",
                                EXPERIMENT,
                                "--model",
                                MODEL,
                                "--schema",
                                f"{CATALOG}.{SCHEMA}",
                                "--job-id",
                                "{{job.id}}",
                                "--job-run-id",
                                "{{job.run_id}}",
                            ]
                        ),
                    },
                ),
            )
        ],
    }


def find_job(w, name: str) -> int | None:
    for job in w.jobs.list(name=name):
        return job.job_id
    return None


def main() -> int:
    w = workspace_client()
    uploaded = upload_code(w)
    print("code uploaded:", uploaded)
    settings = job_settings(f"{CODE_DIR}/train_quality.py")
    job_id = find_job(w, JOB_NAME)
    if job_id is None:
        job_id = w.jobs.create(**settings).job_id
        print(f"job created: {JOB_NAME} (job_id {job_id})")
    else:
        w.jobs.reset(job_id, jobs.JobSettings(**settings))
        print(f"job updated: {JOB_NAME} (job_id {job_id})")

    active = [r for r in w.jobs.list_runs(job_id=job_id, active_only=True)]
    if active:
        print(f"a run is already active ({active[0].run_id}): not starting another one")
        return 1
    run_id = w.jobs.run_now(job_id).run_id
    print(f"run started: run_id {run_id}")
    start, last = time.time(), None
    while True:
        run = w.jobs.get_run(run_id)
        state = (
            run.state.life_cycle_state.value,
            run.state.result_state.value if run.state.result_state else None,
        )
        if state != last:
            print(f"  [{int(time.time() - start):>4}s] {state[0]} {state[1] or ''}", flush=True)
            last = state
        if run.state.life_cycle_state.value in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            break
        if time.time() - start > MAX_WAIT_S:
            print("timeout reached: cancelling the run")
            w.jobs.cancel_run(run_id)
            break
        time.sleep(20)

    task_run_id = run.tasks[0].run_id
    output = w.jobs.get_run_output(task_run_id)
    logs = output.logs or ""
    summary = None
    for line in logs.splitlines():
        if line.startswith("ARGOS_RESULT="):
            summary = json.loads(line.removeprefix("ARGOS_RESULT="))
    if summary is None:
        try:
            summary = json.load(w.files.download(f"{VOLUME_PATH}/runs/{run_id}.json").contents)
        except Exception as exc:  # noqa: BLE001
            print("no summary available:", exc)
    result = {
        "job_id": job_id,
        "run_id": run_id,
        "task_run_id": task_run_id,
        "life_cycle_state": run.state.life_cycle_state.value,
        "result_state": run.state.result_state.value if run.state.result_state else None,
        "state_message": run.state.state_message,
        "duration_s": round(((run.end_time or 0) - (run.start_time or 0)) / 1000, 1),
        "run_page_url": run.run_page_url,
        "error": output.error,
        "error_trace_tail": (output.error_trace or "")[-3000:],
        "logs_tail": logs[-3000:],
        "summary": summary,
    }
    path = save_result("training_job", result)
    print(f"result: {result['result_state']} in {result['duration_s']} s - saved to {path}")
    if output.error:
        print("ERROR:", output.error)
        print((output.error_trace or "")[-2500:])
    elif logs:
        print("--- logs tail ---\n" + logs[-1500:])
    return 0 if result["result_state"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
