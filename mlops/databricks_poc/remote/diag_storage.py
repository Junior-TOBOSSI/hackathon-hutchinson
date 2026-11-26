# Databricks notebook source
# ruff: noqa: F821  (spark and dbutils are globals injected by Databricks notebooks)
# DBX-00 storage diagnostic: which read paths work from serverless compute?
import json
import os
import platform

VOLUME = "/Volumes/workspace/argos_poc/images"
results = {"python": platform.python_version()}


def check(name, call):
    try:
        value = call()
        results[name] = {"ok": True, "detail": str(value)[:300]}
    except Exception as exc:  # noqa: BLE001
        results[name] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


check("os.listdir(volume)", lambda: os.listdir(VOLUME))
check(
    "open(volume manifest)", lambda: len(open(f"{VOLUME}/synthetic-v1/manifest.json", "rb").read())
)
check(
    "open(volume png)", lambda: len(open(f"{VOLUME}/synthetic-v1/test/OK/ok_000.png", "rb").read())
)
check("dbutils.fs.ls(volume)", lambda: [f.name for f in dbutils.fs.ls(VOLUME)])  # noqa: F821
check(
    "spark binaryFile(volume)",
    lambda: spark.read.format("binaryFile").load(f"{VOLUME}/synthetic-v1/test/OK").count(),
)  # noqa: F821
check("spark.sql(select 1)", lambda: spark.sql("select 1 as x").collect()[0].x)  # noqa: F821
check(
    "spark write delta table",
    lambda: (
        spark.createDataFrame([(1, "a")], "id INT, v STRING")
        .write.mode("overwrite")
        .saveAsTable("workspace.argos_poc.diag_probe")
    ),
)  # noqa: F821
check("spark read delta table", lambda: spark.table("workspace.argos_poc.diag_probe").count())  # noqa: F821
check(
    "open(/Workspace/Shared file)",
    lambda: len(open("/Workspace/Shared/ARGOS-POC/code/train_quality.py", "rb").read()),
)


def sdk_download():
    from databricks.sdk import WorkspaceClient

    return len(
        WorkspaceClient().files.download(f"{VOLUME}/synthetic-v1/manifest.json").contents.read()
    )


check("sdk files.download(volume)", sdk_download)


def mlflow_probe():
    import mlflow

    mlflow.set_tracking_uri("databricks")
    exp = mlflow.set_experiment("/Shared/ARGOS-POC/diag-probe")
    with mlflow.start_run(run_name="diag") as run:
        mlflow.log_metric("probe", 1.0)
        mlflow.log_dict({"ok": True}, "probe.json")
    return {"experiment": exp.experiment_id, "run": run.info.run_id}


check("mlflow run + artifact", mlflow_probe)
print("ARGOS_RESULT=" + json.dumps(results))
dbutils.notebook.exit(json.dumps(results))  # noqa: F821
