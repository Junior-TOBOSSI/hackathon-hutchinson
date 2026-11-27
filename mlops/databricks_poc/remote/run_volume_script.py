# Databricks notebook source
# ruff: noqa: F821  (spark and dbutils are globals injected by Databricks notebooks)
# Generic launcher: runs a Python script stored in a Unity Catalog Volume with arguments.
# Why: on this trial workspace, serverless compute cannot read Workspace files
# (403 SSE-C) and spark_python_task refuses Volume paths, but notebooks and Volumes work.
import json
import sys

dbutils.widgets.text("script", "")  # noqa: F821
dbutils.widgets.text("args", "[]")  # noqa: F821
script = dbutils.widgets.get("script")  # noqa: F821
sys.argv = [script, *json.loads(dbutils.widgets.get("args"))]  # noqa: F821
with open(script, encoding="utf-8") as handle:
    exec(
        compile(handle.read(), script, "exec"),
        {"__name__": "__main__", "spark": spark, "dbutils": dbutils},
    )  # noqa: F821, S102
