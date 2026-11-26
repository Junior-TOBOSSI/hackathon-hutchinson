"""DBX-00C/D: training job executed ON DATABRICKS (serverless CPU), triggered from the PC.

Steps: read the manifest and images from the Unity Catalog Volume, verify the splits and
SHA-256, write the Delta tables ``annotations`` and ``dataset_versions``, train two real
configurations, log them to MLflow, select on VALIDATION, evaluate the test split only
afterwards, register both models in Unity Catalog with aliases champion / challenger, and
write a JSON summary to the Volume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime

VERSION_PATTERN = r"^[a-z0-9][a-z0-9-]{1,40}$"


def delta_write_options(table_exists: bool, dataset_version: str) -> dict[str, str]:
    """DBX-04 (option B): Delta writes targeted at ONE dataset version.

    Re-running a training on the same version replaces only that version's rows
    (idempotent, no duplicates); rows of every other version are kept. The first write
    creates the table. The version name is validated because it goes into a predicate.
    """
    import re

    if not re.match(VERSION_PATTERN, dataset_version):
        raise ValueError(f"invalid dataset version {dataset_version!r}")
    if not table_exists:
        return {}
    return {"replaceWhere": f"dataset_version = '{dataset_version}'"}


def write_version_rows(spark, frame, table: str, dataset_version: str) -> None:
    options = delta_write_options(spark.catalog.tableExists(table), dataset_version)
    writer = spark.createDataFrame(frame).write.mode("overwrite")
    for key, value in options.items():
        writer = writer.option(key, value)
    writer.saveAsTable(table)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in (
        "code-dir",
        "dataset-dir",
        "experiment",
        "model",
        "schema",
        "job-id",
        "job-run-id",
    ):
        parser.add_argument(f"--{name}", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.path.insert(0, args.code_dir)
    import base64

    import joblib
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mlflow
    import numpy as np
    import pandas as pd
    import sklearn
    from mlflow.models import infer_signature
    from pyspark.sql import SparkSession
    from quality_model import features_from_bytes
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        ConfusionMatrixDisplay,
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    versions = {
        "mlflow": mlflow.__version__,
        "scikit-learn": sklearn.__version__,
        "python": sys.version.split()[0],
    }
    print("runtime versions:", versions)
    # The served/local model pins these versions: training with others would break the promise.
    assert versions["mlflow"] == "3.18.0" and versions["scikit-learn"] == "1.9.1", (
        f"unexpected versions {versions}"
    )
    started = time.time()
    # ---------------------------------------------------------------- data from the Volume
    manifest_path = f"{args.dataset_dir}/manifest.json"
    with open(manifest_path, "rb") as handle:
        manifest_bytes = handle.read()
    manifest = json.loads(manifest_bytes)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    items = manifest["items"]
    files_by_split = {
        s: {i["file"] for i in items if i["split"] == s} for s in ("train", "validation", "test")
    }
    assert not (files_by_split["train"] & files_by_split["validation"]), "train/validation overlap"
    assert not (files_by_split["train"] & files_by_split["test"]), "train/test overlap"
    assert not (files_by_split["validation"] & files_by_split["test"]), "validation/test overlap"

    raw, bad_hashes = {}, []
    for item in items:
        with open(f"{args.dataset_dir}/{item['file']}", "rb") as handle:
            content = handle.read()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            bad_hashes.append(item["file"])
        raw[item["file"]] = content
    assert not bad_hashes, f"SHA-256 mismatch: {bad_hashes[:5]}"
    print(
        f"Loaded {len(raw)} images from {args.dataset_dir}; splits {manifest['counts']}; sha256 OK"
    )

    def split_xy(split):
        selected = [i for i in items if i["split"] == split]
        X = np.stack([features_from_bytes(raw[i["file"]]) for i in selected])
        return X, np.array([i["label"] for i in selected])

    X_train, y_train = split_xy("train")
    X_val, y_val = split_xy("validation")
    X_test, y_test = split_xy("test")

    # ---------------------------------------------------------------- Delta tables
    spark = SparkSession.builder.getOrCreate()
    annotations = pd.DataFrame(
        [
            {
                "file": i["file"],
                "label": i["label"],
                "split": i["split"],
                "sha256": i["sha256"],
                "brightness": i.get("brightness"),
                "noise": i.get("noise"),
                "defect": i.get("defect") or "",
                "dataset_version": manifest["dataset_version"],
            }
            for i in items
        ]
    )
    # One dataset version per write: the other versions' rows are kept (DBX-04 option B).
    write_version_rows(
        spark, annotations, f"{args.schema}.annotations", manifest["dataset_version"]
    )
    versions = pd.DataFrame(
        [
            {
                "dataset_version": manifest["dataset_version"],
                "volume_path": args.dataset_dir,
                "manifest_sha256": manifest_sha,
                "n_images": len(items),
                "seed": manifest["seed"],
                "counts_json": json.dumps(manifest["counts"]),
                "synthetic": bool(manifest.get("synthetic", True)),
                "registered_at": datetime.now(UTC).isoformat(),
            }
        ]
    )
    write_version_rows(
        spark, versions, f"{args.schema}.dataset_versions", manifest["dataset_version"]
    )
    print(
        f"Delta tables written: {args.schema}.annotations ({len(annotations)} rows), "
        f"{args.schema}.dataset_versions"
    )

    # ---------------------------------------------------------------- training + MLflow
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    experiment = mlflow.set_experiment(args.experiment)
    configs = [
        {"run_name": "logreg-C0.1", "C": 0.1, "max_iter": 3000},
        {"run_name": "logreg-C10", "C": 10.0, "max_iter": 3000},
    ]
    dataset_input = mlflow.data.from_pandas(
        annotations, name=f"argos-poc-{manifest['dataset_version']}", source=args.dataset_dir
    )
    example = pd.DataFrame({"image_base64": [base64.b64encode(raw[items[0]["file"]]).decode()]})
    code_file = os.path.join(args.code_dir, "quality_model.py")

    def metrics_for(model, X, y, prefix):
        predicted = model.predict(X)
        return {
            f"{prefix}_accuracy": accuracy_score(y, predicted),
            f"{prefix}_precision_nok": precision_score(
                y, predicted, pos_label="NOK", zero_division=0
            ),
            f"{prefix}_recall_nok": recall_score(y, predicted, pos_label="NOK", zero_division=0),
            f"{prefix}_f1_nok": f1_score(y, predicted, pos_label="NOK", zero_division=0),
        }, confusion_matrix(y, predicted, labels=["OK", "NOK"]).tolist()

    results = []
    for config in configs:
        with mlflow.start_run(run_name=config["run_name"]) as run:
            mlflow.set_tags(
                {
                    "synthetic": "true",
                    "argos.poc": "DBX-00",
                    "argos.dataset_version": manifest["dataset_version"],
                    "argos.manifest_sha256": manifest_sha,
                    "databricks.job_id": args.job_id,
                    "databricks.job_run_id": args.job_run_id,
                }
            )
            mlflow.log_params(
                {
                    "model": "StandardScaler + LogisticRegression",
                    "C": config["C"],
                    "max_iter": config["max_iter"],
                    "features": "29 shape features (gradient orientations + edge profiles)",
                    "dataset_version": manifest["dataset_version"],
                    "n_train": len(y_train),
                    "n_validation": len(y_val),
                    "n_test": len(y_test),
                }
            )
            mlflow.log_input(dataset_input, context="training")
            t0 = time.time()
            model = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "clf",
                        LogisticRegression(
                            C=config["C"], max_iter=config["max_iter"], random_state=0
                        ),
                    ),
                ]
            ).fit(X_train, y_train)
            val_metrics, val_matrix = metrics_for(model, X_val, y_val, "val")
            val_metrics["train_time_s"] = time.time() - t0
            mlflow.log_metrics(val_metrics)
            mlflow.log_dict(
                {"labels": ["OK", "NOK"], "matrix": val_matrix, "split": "validation"},
                "reports/confusion_matrix_val.json",
            )
            figure, axis = plt.subplots(figsize=(3.5, 3.2))
            ConfusionMatrixDisplay(np.array(val_matrix), display_labels=["OK", "NOK"]).plot(
                ax=axis, colorbar=False
            )
            axis.set_title(f"{config['run_name']} (validation)")
            mlflow.log_figure(figure, "reports/confusion_matrix_val.png")
            plt.close(figure)
            mlflow.log_dict(manifest["counts"], "dataset/split_counts.json")

            tmp = tempfile.mkdtemp()
            joblib.dump(model, os.path.join(tmp, "classifier.joblib"))
            with open(os.path.join(tmp, "metadata.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "nok_label": "NOK",
                        "decision_threshold": 0.5,
                        "features": "quality_model.FEATURE_NAMES",
                        "dataset_version": manifest["dataset_version"],
                    },
                    handle,
                )
            signature = infer_signature(
                example, pd.DataFrame({"class": ["OK"], "anomaly_score": [0.1]})
            )
            info = mlflow.pyfunc.log_model(
                name="model",
                python_model=code_file,
                artifacts={
                    "classifier": os.path.join(tmp, "classifier.joblib"),
                    "metadata": os.path.join(tmp, "metadata.json"),
                },
                signature=signature,
                input_example=example,
                pip_requirements=[
                    "mlflow==3.18.0",
                    "scikit-learn==1.9.1",
                    "numpy==2.4.6",
                    "pandas==3.1.1",
                    "pillow==13.0.0",
                    "joblib",
                ],
            )
            print(f"{config['run_name']}: run {run.info.run_id} val {val_metrics}")
            results.append(
                {
                    **config,
                    "run_id": run.info.run_id,
                    "model_uri": info.model_uri,
                    "model_id": info.model_id,
                    "val": val_metrics,
                    "model": model,
                }
            )

    # ---------------------------------------------------------------- selection on validation
    ranked = sorted(
        results, key=lambda r: (r["val"]["val_f1_nok"], r["val"]["val_recall_nok"]), reverse=True
    )
    for role, result in (("champion", ranked[0]), ("challenger", ranked[1])):
        test_metrics, test_matrix = metrics_for(result["model"], X_test, y_test, "test")
        with mlflow.start_run(run_id=result["run_id"]):
            mlflow.log_metrics(test_metrics)
            mlflow.log_dict(
                {"labels": ["OK", "NOK"], "matrix": test_matrix, "split": "test"},
                "reports/confusion_matrix_test.json",
            )
            mlflow.set_tags(
                {"argos.selection_role": role, "argos.test_evaluated_after_selection": "true"}
            )
        result["test"], result["role"] = test_metrics, role

    client = mlflow.MlflowClient()
    for result in results:  # registration in training order
        version = mlflow.register_model(result["model_uri"], args.model)
        # Unity Catalog tag keys cannot contain "." (run tags can): underscores here.
        for key, value in (
            ("argos_selection_role", result["role"]),
            ("databricks_job_run_id", args.job_run_id),
            ("argos_dataset_version", manifest["dataset_version"]),
            ("synthetic", "true"),
        ):
            client.set_model_version_tag(args.model, version.version, key, value)
        client.set_registered_model_alias(args.model, result["role"], version.version)
        result["version"] = version.version
        print(
            f"registered {args.model} v{version.version} ({result['role']}) "
            f"from run {result['run_id']}"
        )

    summary = {
        "job_id": args.job_id,
        "job_run_id": args.job_run_id,
        "experiment_id": experiment.experiment_id,
        "experiment": args.experiment,
        "model": args.model,
        "dataset_version": manifest["dataset_version"],
        "manifest_sha256": manifest_sha,
        "duration_s": round(time.time() - started, 1),
        "runs": [{k: v for k, v in r.items() if k != "model"} for r in results],
    }
    out = f"{os.path.dirname(args.dataset_dir)}/runs/{args.job_run_id}.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
    print("ARGOS_RESULT=" + json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
