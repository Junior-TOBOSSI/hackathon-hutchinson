"""DBX-00H: telemetry to Delta, drift job on Databricks, results read back from the PC.

    python -m mlops.databricks_poc.monitoring local-telemetry --version 1   # local model only
    python -m mlops.databricks_poc.monitoring push                          # SQL warehouse -> Delta
    python -m mlops.databricks_poc.monitoring dqm-check                     # native monitoring?
    python -m mlops.databricks_poc.monitoring drift-job                     # serverless job (PSI)
    python -m mlops.databricks_poc.monitoring report                        # read results via SQL
    python -m mlops.databricks_poc.monitoring stop-warehouse                # only if WE started it

Telemetry sources are explicit: ``serving`` = real remote inferences (simulator),
``local_model`` = the same registered model evaluated locally on more images (to get a
usable distribution without exceeding the 20 remote inference budget).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

from mlops.databricks_poc.common import (
    LOCAL_DATASET,
    LOCAL_HOME,
    MONITOR_JOB_NAME,
    TABLE_ANNOTATIONS,
    TABLE_DATASET_VERSIONS,
    TABLE_DRIFT,
    TABLE_TELEMETRY,
    VOLUME_PATH,
    save_result,
    workspace_client,
)
from mlops.databricks_poc.simulator import TELEMETRY, drifted_image, image_stats

WAREHOUSE_STATE = LOCAL_HOME / "warehouse_started_by_poc.json"
COLUMNS = [
    ("station_id", "STRING"),
    ("cycle_id", "STRING"),
    ("ts", "TIMESTAMP"),
    ("model_version", "STRING"),
    ("brightness", "DOUBLE"),
    ("blur", "DOUBLE"),
    ("anomaly_score", "DOUBLE"),
    ("predicted_label", "STRING"),
    ("ground_truth", "STRING"),
    ("latency_ms", "DOUBLE"),
    ("scenario", "STRING"),
    ("source", "STRING"),
    ("verdict", "STRING"),
]


# --------------------------------------------------------------------------- SQL warehouse


def warehouse(w):
    return next(iter(w.warehouses.list()))


def ensure_warehouse(w) -> str:
    wh = warehouse(w)
    if wh.state.value != "RUNNING":
        print(f"starting warehouse {wh.name} ({wh.state.value}) ...")
        WAREHOUSE_STATE.write_text(
            json.dumps({"id": wh.id, "started_at": time.time()}), encoding="utf-8"
        )
        w.warehouses.start(wh.id).result(timeout=timedelta(minutes=10))
    return wh.id


def sql(w, warehouse_id: str, statement: str) -> list[list]:
    response = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=warehouse_id, wait_timeout="50s"
    )
    deadline = time.time() + 300
    while response.status.state.value in ("PENDING", "RUNNING") and time.time() < deadline:
        time.sleep(3)
        response = w.statement_execution.get_statement(response.statement_id)
    if response.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"SQL failed ({response.status.state.value}): {response.status.error}")
    return (response.result.data_array or []) if response.result else []


def literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(float(value))
    return "'" + str(value).replace("'", "''") + "'"


# --------------------------------------------------------------------------- commands


def local_telemetry(version: str, count: int = 40) -> int:
    import pandas as pd

    from mlops.databricks_poc.inference import load_local

    model = load_local(version)
    manifest = json.loads((LOCAL_DATASET / "manifest.json").read_text(encoding="utf-8"))
    reference = [i for i in manifest["items"] if i["split"] == "test"][:count]
    rng = np.random.default_rng(1_234)
    rows = []
    for scenario in ("reference", "drift"):
        images = [
            (
                (LOCAL_DATASET / i["file"]).read_bytes()
                if scenario == "reference"
                else drifted_image(i["label"], rng),
                i["label"],
            )
            for i in reference
        ]
        start = time.perf_counter()
        predictions = model.predict(
            pd.DataFrame({"image_base64": [base64.b64encode(p).decode() for p, _ in images]})
        )
        per_image_ms = (time.perf_counter() - start) * 1000 / len(images)
        for index, (png, truth) in enumerate(images):
            rows.append(
                {
                    "station_id": "LOCAL-EVAL",
                    "cycle_id": f"local-{scenario}-{index:03d}",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                    "model_version": version,
                    **image_stats(png),
                    "anomaly_score": float(predictions["anomaly_score"].iloc[index]),
                    "predicted_label": predictions["class"].iloc[index],
                    "ground_truth": truth,
                    "latency_ms": per_image_ms,
                    "scenario": scenario,
                    "source": "local_model",
                    "verdict": None,
                }
            )
    with TELEMETRY.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    for scenario in ("reference", "drift"):
        part = [r for r in rows if r["scenario"] == scenario]
        acc = sum(r["predicted_label"] == r["ground_truth"] for r in part) / len(part)
        print(
            f"{scenario:<9} n={len(part)} "
            f"mean brightness={np.mean([r['brightness'] for r in part]):.3f} "
            f"accuracy={acc:.3f} mean score={np.mean([r['anomaly_score'] for r in part]):.3f}"
        )
    print(f"{len(rows)} local-model telemetry rows appended to {TELEMETRY}")
    return 0


def push() -> int:
    w = workspace_client()
    wid = ensure_warehouse(w)
    rows = [
        json.loads(line)
        for line in TELEMETRY.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    columns = ", ".join(f"{name} {kind}" for name, kind in COLUMNS)
    sql(
        w,
        wid,
        f"CREATE OR REPLACE TABLE {TABLE_TELEMETRY} ({columns}) "
        "COMMENT 'ARGOS DBX-00 POC telemetry (synthetic)'",
    )
    values = ",\n".join(
        "("
        + ", ".join(
            f"CAST({literal(row.get(name))} AS TIMESTAMP)"
            if kind == "TIMESTAMP"
            else literal(row.get(name))
            for name, kind in COLUMNS
        )
        + ")"
        for row in rows
    )
    sql(w, wid, f"INSERT INTO {TABLE_TELEMETRY} VALUES {values}")
    counts = sql(
        w,
        wid,
        "SELECT source, scenario, COUNT(*), ROUND(AVG(brightness), 3), "
        "ROUND(AVG(anomaly_score), 3) "
        f"FROM {TABLE_TELEMETRY} GROUP BY source, scenario ORDER BY source, scenario",
    )
    annotations = sql(
        w,
        wid,
        f"SELECT split, label, COUNT(*) FROM {TABLE_ANNOTATIONS} "
        "GROUP BY split, label ORDER BY split, label",
    )
    versions = sql(
        w, wid, f"SELECT dataset_version, n_images, manifest_sha256 FROM {TABLE_DATASET_VERSIONS}"
    )
    print("telemetry (source, scenario, n, mean brightness, mean score):", counts)
    print("annotations read from the PC:", annotations)
    print("dataset_versions read from the PC:", versions)
    save_result(
        "telemetry_push",
        {
            "rows_pushed": len(rows),
            "telemetry": counts,
            "annotations": annotations,
            "dataset_versions": versions,
        },
    )
    return 0


def dqm_check() -> int:
    """Is native data quality monitoring usable? Create a minimal monitor, then remove it."""
    from databricks.sdk.service.catalog import MonitorSnapshot

    w = workspace_client()
    me = w.current_user.me().user_name
    result: dict = {}
    try:
        info = w.quality_monitors.create(
            table_name=TABLE_TELEMETRY,
            assets_dir=f"/Workspace/Users/{me}/argos_poc_monitoring",
            output_schema_name="workspace.argos_poc",
            snapshot=MonitorSnapshot(),
            skip_builtin_dashboard=True,
        )
        result = {"create": "OK", "status": str(info.status)}
        time.sleep(10)
        result["status_after_10s"] = str(w.quality_monitors.get(TABLE_TELEMETRY).status)
        w.quality_monitors.delete(TABLE_TELEMETRY)
        result["deleted"] = True
    except Exception as exc:  # noqa: BLE001 - we want the exact refusal
        result = {"create": "FAILED", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
    print(result)
    save_result("dqm_check", result)
    return 0


def drift_job() -> int:
    from databricks.sdk.service import compute, jobs

    from mlops.databricks_poc.run_training_job import LAUNCHER, upload_code

    w = workspace_client()
    code_dir = f"{VOLUME_PATH}/code"  # Volume, not workspace files (see run_training_job.py)
    with (Path(__file__).parent / "remote" / "drift_monitor.py").open("rb") as handle:
        w.files.upload(f"{code_dir}/drift_monitor.py", handle, overwrite=True)
    upload_code(w)  # also (re)imports the launcher notebook
    settings = {
        "name": MONITOR_JOB_NAME,
        "max_concurrent_runs": 1,
        "timeout_seconds": 1800,
        "tags": {"argos": "dbx-00-poc", "synthetic": "true"},
        "environments": [
            jobs.JobEnvironment(
                environment_key="default", spec=compute.Environment(environment_version="3")
            )
        ],
        "tasks": [
            jobs.Task(
                task_key="drift",
                environment_key="default",
                timeout_seconds=1200,
                max_retries=0,
                notebook_task=jobs.NotebookTask(
                    notebook_path=LAUNCHER,
                    base_parameters={
                        "script": f"{code_dir}/drift_monitor.py",
                        "args": json.dumps(
                            [
                                "--telemetry",
                                TABLE_TELEMETRY,
                                "--report",
                                TABLE_DRIFT,
                                "--job-run-id",
                                "{{job.run_id}}",
                            ]
                        ),
                    },
                ),
            )
        ],
    }
    job_id = next((j.job_id for j in w.jobs.list(name=MONITOR_JOB_NAME)), None)
    if job_id is None:
        job_id = w.jobs.create(**settings).job_id
    else:
        w.jobs.reset(job_id, jobs.JobSettings(**settings))
    run_id = w.jobs.run_now(job_id).run_id
    print(f"drift job {job_id} run {run_id} started")
    start = time.time()
    while True:
        run = w.jobs.get_run(run_id)
        if (
            run.state.life_cycle_state.value in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR")
            or time.time() - start > 1500
        ):
            break
        time.sleep(20)
    output = w.jobs.get_run_output(run.tasks[0].run_id)
    result = {
        "job_id": job_id,
        "run_id": run_id,
        "result_state": run.state.result_state.value if run.state.result_state else None,
        "duration_s": round(((run.end_time or 0) - (run.start_time or 0)) / 1000, 1),
        "error": output.error,
        "logs_tail": (output.logs or "")[-2000:],
        "error_trace_tail": (output.error_trace or "")[-2000:],
    }
    save_result("drift_job", result)
    print(f"drift job: {result['result_state']} in {result['duration_s']} s")
    if output.error:
        print(output.error, (output.error_trace or "")[-1500:])
    return 0 if result["result_state"] == "SUCCESS" else 1


def report() -> int:
    w = workspace_client()
    wid = ensure_warehouse(w)
    rows = sql(
        w,
        wid,
        f"SELECT feature, method, ROUND(value, 4), threshold, alert, ROUND(reference_mean, 4), "
        f"ROUND(current_mean, 4), n_reference, n_current FROM {TABLE_DRIFT} ORDER BY feature",
    )
    print("feature | method | value | threshold | alert | ref mean | cur mean | n_ref | n_cur")
    for row in rows:
        print(" | ".join(str(v) for v in row))
    save_result("drift_report", {"rows": rows})
    return 0


def stop_warehouse() -> int:
    w = workspace_client()
    wh = warehouse(w)
    if not WAREHOUSE_STATE.exists():
        print(f"warehouse {wh.name} was not started by the POC ({wh.state.value}): left as is")
        return 0
    w.warehouses.stop(wh.id).result(timeout=timedelta(minutes=10))
    WAREHOUSE_STATE.unlink()
    print(f"warehouse {wh.name} stopped: {warehouse(w).state.value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("local-telemetry").add_argument("--version", required=True)
    for name in ("push", "dqm-check", "drift-job", "report", "stop-warehouse"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    workspace_client()
    return {
        "local-telemetry": lambda: local_telemetry(args.version),
        "push": push,
        "dqm-check": dqm_check,
        "drift-job": drift_job,
        "report": report,
        "stop-warehouse": stop_warehouse,
    }[args.command]()


if __name__ == "__main__":
    sys.exit(main())
