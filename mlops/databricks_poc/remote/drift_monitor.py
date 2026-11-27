"""DBX-00H: drift computation executed ON DATABRICKS (replacement for native monitoring).

Reads the telemetry Delta table, compares the ``drift`` scenario to the ``reference``
scenario with the Population Stability Index (PSI, 10 quantile bins of the reference) and
the mean shift, for brightness, blur and anomaly_score, and overwrites the drift_report
Delta table. PSI > 0.2 is flagged as a significant DATA drift on that feature.

This is a data drift indicator only: a brightness change is not a concept drift (the
relation between image and label did not change).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime


def psi(reference, current, bins: int = 10) -> float:
    import numpy as np

    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        edges = np.linspace(
            min(reference.min(), current.min()), max(reference.max(), current.max()), bins + 1
        )
    edges[0], edges[-1] = -np.inf, np.inf
    ref = np.histogram(reference, edges)[0] / len(reference)
    cur = np.histogram(current, edges)[0] / len(current)
    ref, cur = np.clip(ref, 1e-4, None), np.clip(cur, 1e-4, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--job-run-id", required=True)
    args = parser.parse_args()

    import pandas as pd
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    frame = spark.table(args.telemetry).toPandas()
    frame = frame[frame["anomaly_score"].notna()]
    reference = frame[frame["scenario"] == "reference"]
    current = frame[frame["scenario"] == "drift"]
    rows = []
    for feature in ("brightness", "blur", "anomaly_score"):
        r, c = (
            reference[feature].astype(float).to_numpy(),
            current[feature].astype(float).to_numpy(),
        )
        value = psi(r, c)
        rows.append(
            {
                "feature": feature,
                "method": "psi",
                "value": value,
                "threshold": 0.2,
                "alert": value > 0.2,
                "reference_mean": float(r.mean()),
                "current_mean": float(c.mean()),
                "n_reference": int(len(r)),
                "n_current": int(len(c)),
                "computed_at": datetime.now(UTC).isoformat(),
                "job_run_id": args.job_run_id,
            }
        )
    for scenario, part in (("reference", reference), ("drift", current)):
        known = part[part["ground_truth"].notna()]
        accuracy = (
            float((known["predicted_label"] == known["ground_truth"]).mean())
            if len(known)
            else None
        )
        rows.append(
            {
                "feature": f"accuracy_{scenario}",
                "method": "labelled_accuracy",
                "value": accuracy,
                "threshold": None,
                "alert": False,
                "reference_mean": None,
                "current_mean": None,
                "n_reference": int(len(known)),
                "n_current": int(len(known)),
                "computed_at": datetime.now(UTC).isoformat(),
                "job_run_id": args.job_run_id,
            }
        )
    report = pd.DataFrame(rows)
    spark.createDataFrame(report).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(args.report)
    print("ARGOS_RESULT=" + json.dumps(rows, default=str))


if __name__ == "__main__":
    main()
