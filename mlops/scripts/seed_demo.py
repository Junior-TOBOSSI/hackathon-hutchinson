"""Seed the ARGOS Foundation demo in MLflow: real trainings, artifacts, registry, aliases.

    python -m mlops.scripts.seed_demo            # does nothing if the demo already exists
    python -m mlops.scripts.seed_demo --force    # adds a new batch of runs and versions

Steps:
1. experiment ``argos-foundation-demo`` (tag synthetic=true);
2. one run per configuration of ``mlops.demo.training.TRAINING_CONFIGS``: params, tags,
   dataset inputs, real metric histories, validation metrics, artifacts, Logged Model;
3. selection on VALIDATION macro-F1 (the test split is never used to choose);
4. test metrics computed only for the two selected runs, after the selection;
5. registered model ``argos-foundation-demo-model``: one version per selected run,
   aliases ``champion`` (best) and ``challenger`` (second).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import mlflow.data  # noqa: E402
import mlflow.sklearn  # noqa: E402
import numpy as np  # noqa: E402
from mlflow.entities import Metric  # noqa: E402
from mlflow.models import infer_signature  # noqa: E402
from sklearn.metrics import ConfusionMatrixDisplay  # noqa: E402

from mlops.config import DEMO_EXPERIMENT, DEMO_MODEL, MlflowSettings, utf8_console  # noqa: E402
from mlops.connectors import ArgosMlflowConnector, RegisteredModelNotFoundError  # noqa: E402
from mlops.demo.data import CLASSES, SPLIT, SyntheticDataset, make_dataset  # noqa: E402
from mlops.demo.training import TRAINING_CONFIGS, evaluate, train  # noqa: E402

SELECTION_METRIC = "val_f1_macro"
TRUSTED_TYPES = {
    "random_forest": ["sklearn.tree._tree.Tree"],
    "gradient_boosting": ["sklearn.tree._tree.Tree"],
}
COMMON_TAGS = {
    "synthetic": "true",
    "argos.project": "argos",
    "argos.workstream": "mlops",
    "argos.purpose": "MLOPS-01 foundation demo (pedagogical, not an industrial model)",
}


def git_info() -> dict[str, str]:
    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], capture_output=True, text=True, check=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    return {
        "argos.git_commit": git("rev-parse", "HEAD"),
        "argos.git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "argos.git_dirty": str(bool(git("status", "--porcelain"))).lower(),
    }


def log_history(client: mlflow.MlflowClient, run_id: str, history: dict) -> int:
    """Log real per-step histories in batches (log_batch accepts up to 1000 metrics)."""
    now = int(time.time() * 1000)
    metrics = [
        Metric(key=f"history_{key}", value=float(value), timestamp=now, step=int(step))
        for key, points in history.items()
        for step, value in points
    ]
    for start in range(0, len(metrics), 1000):
        client.log_batch(run_id, metrics=metrics[start : start + 1000])
    return len(metrics)


def confusion_figure(matrix: list[list[int]], title: str):
    figure, axis = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay(confusion_matrix=np.array(matrix), display_labels=CLASSES).plot(
        ax=axis, colorbar=False
    )
    axis.set_title(title)
    figure.tight_layout()
    return figure


def run_training(config: dict, data: SyntheticDataset, datasets: dict, git: dict) -> dict:
    client = mlflow.MlflowClient()
    with mlflow.start_run(run_name=config["run_name"]) as run:
        mlflow.set_tags({**COMMON_TAGS, **git, "argos.model_family": config["family"]})
        mlflow.log_params(
            {
                "architecture": config["architecture"],
                "model_family": config["family"],
                "seed": config["seed"],
                **{f"hp_{k}": v for k, v in config["hyperparameters"].items()},
                "dataset_name": data.info["name"],
                "dataset_seed": data.info["seed"],
                "dataset_n_samples": data.info["generator_params"]["n_samples"],
                "dataset_n_features": data.info["generator_params"]["n_features"],
                "split_strategy": data.info["split_strategy"],
                "split_ratios": json.dumps(SPLIT),
                "split_train_size": data.info["split_sizes"]["train"],
                "split_validation_size": data.info["split_sizes"]["validation"],
                "split_test_size": data.info["split_sizes"]["test"],
                "selection_metric": SELECTION_METRIC,
            }
        )
        mlflow.log_input(datasets["train"], context="training")
        mlflow.log_input(datasets["validation"], context="validation")

        trained = train(config, data)
        n_history = log_history(client, run.info.run_id, trained.history)
        metrics, report, matrix = evaluate(trained.model, data.X_val, data.y_val, "val")
        metrics["train_time_s"] = trained.train_time_s

        mlflow.log_dict({**config, "dataset": data.info["name"]}, "config/config.json")
        mlflow.log_dict(report, "reports/classification_report.json")
        mlflow.log_dict(
            {"labels": CLASSES, "matrix": matrix, "split": "validation"},
            "reports/confusion_matrix.json",
        )
        figure = confusion_figure(matrix, f"{config['run_name']} (validation)")
        mlflow.log_figure(figure, "reports/confusion_matrix.png")
        plt.close(figure)
        mlflow.log_dict(data.info, "dataset/dataset_info.json")

        sample = data.X_val.head(20)
        model_info = mlflow.sklearn.log_model(
            trained.model,
            name="model",
            signature=infer_signature(sample, trained.model.predict(sample)),
            input_example=data.X_val.head(3),
            tags={"synthetic": "true", "argos.model_family": config["family"]},
            # MLflow 3.18 serializes sklearn models with skops, which refuses tree internals
            # unless trusted. We trust ONLY this type, for models we have just trained.
            skops_trusted_types=TRUSTED_TYPES.get(config["family"]),
        )
        # Logged with model_id: the metrics belong to the run AND to its Logged Model.
        mlflow.log_metrics(metrics, model_id=model_info.model_id, dataset=datasets["validation"])
        print(
            f"  {config['run_name']:<22} {SELECTION_METRIC}={metrics[SELECTION_METRIC]:.4f} "
            f"train={trained.train_time_s:.2f}s history_points={n_history}",
            flush=True,
        )
        return {
            "run_name": config["run_name"],
            "run_id": run.info.run_id,
            "model_id": model_info.model_id,
            "model_uri": model_info.model_uri,
            "family": config["family"],
            "metrics": metrics,
            "model": trained.model,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="add a new batch even if seeded")
    args = parser.parse_args(argv)
    utf8_console()

    settings = MlflowSettings.from_env()
    connector = ArgosMlflowConnector(settings)
    status = connector.ping()
    print(f"MLflow {status.version} at {status.tracking_uri}")
    try:
        existing = connector.get_registered_model(DEMO_MODEL)
        if not args.force:
            print(
                f"Demo already seeded ({DEMO_MODEL}, aliases {existing.aliases}). "
                "Use --force to add a batch."
            )
            return 0
    except RegisteredModelNotFoundError:
        pass

    mlflow.set_tracking_uri(settings.tracking_uri)
    mlflow.set_registry_uri(settings.registry_uri)
    experiment = mlflow.set_experiment(DEMO_EXPERIMENT)
    mlflow.MlflowClient().set_experiment_tag(experiment.experiment_id, "synthetic", "true")
    mlflow.MlflowClient().set_experiment_tag(
        experiment.experiment_id,
        "mlflow.note.content",
        "ARGOS MLOPS-01 pedagogical experiment. SYNTHETIC data (sklearn make_classification), "
        "not an industrial model.",
    )

    data = make_dataset()
    datasets = {
        split: mlflow.data.from_pandas(
            data.frame(split), name=f"{data.info['name']}-{split}", targets="label"
        )
        for split in ("train", "validation", "test")
    }
    git = git_info()
    print(
        f"Experiment {DEMO_EXPERIMENT} (id {experiment.experiment_id}) - "
        f"training {len(TRAINING_CONFIGS)} models"
    )
    results = [run_training(config, data, datasets, git) for config in TRAINING_CONFIGS]

    ranked = sorted(results, key=lambda r: r["metrics"][SELECTION_METRIC], reverse=True)
    champion, challenger = ranked[0], ranked[1]
    client = mlflow.MlflowClient()
    for role, result in (("champion", champion), ("challenger", challenger)):
        # The test split is evaluated only now, AFTER the selection on validation.
        test_metrics, _, test_matrix = evaluate(result["model"], data.X_test, data.y_test, "test")
        with mlflow.start_run(run_id=result["run_id"]):
            mlflow.log_input(datasets["test"], context="test")
            mlflow.log_metrics(test_metrics, model_id=result["model_id"], dataset=datasets["test"])
            mlflow.log_dict(
                {"labels": CLASSES, "matrix": test_matrix, "split": "test"},
                "reports/confusion_matrix_test.json",
            )
            mlflow.set_tags(
                {"argos.selection_role": role, "argos.test_evaluated_after_selection": "true"}
            )
        result["test_metrics"] = test_metrics
    for result in ranked[2:]:
        client.set_tag(result["run_id"], "argos.selection_role", "not_selected")

    # Register in training order, so version numbers follow the chronology of the runs.
    selected_ids = {champion["run_id"], challenger["run_id"]}
    selected = [r for r in results if r["run_id"] in selected_ids]
    versions = {}
    for result in selected:
        version = connector.register_demo_model(
            DEMO_MODEL,
            result["model_id"],
            tags={
                "argos.model_family": result["family"],
                "argos.run_name": result["run_name"],
                SELECTION_METRIC: f"{result['metrics'][SELECTION_METRIC]:.4f}",
            },
            description="ARGOS MLOPS-01 demonstration model trained on SYNTHETIC data. "
            "Not for production.",
        )
        versions[result["run_id"]] = version.version
    connector.set_demo_alias(DEMO_MODEL, "champion", versions[champion["run_id"]])
    connector.set_demo_alias(DEMO_MODEL, "challenger", versions[challenger["run_id"]])

    summary = {
        "experiment": {"name": DEMO_EXPERIMENT, "id": experiment.experiment_id},
        "selection_metric": SELECTION_METRIC,
        "runs": [
            {k: v for k, v in r.items() if k != "model"}
            | {"registered_version": versions.get(r["run_id"])}
            for r in results
        ],
        "registered_model": DEMO_MODEL,
        "aliases": {
            "champion": versions[champion["run_id"]],
            "challenger": versions[challenger["run_id"]],
        },
    }
    out = settings.mlops_home / "logs" / "seed_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"Champion  : {champion['run_name']} -> {DEMO_MODEL} v{versions[champion['run_id']]}")
    print(f"Challenger: {challenger['run_name']} -> {DEMO_MODEL} v{versions[challenger['run_id']]}")
    print(f"Summary written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
