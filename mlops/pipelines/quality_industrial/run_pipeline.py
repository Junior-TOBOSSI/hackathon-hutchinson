"""Remote orchestration of the Quality group's pipeline (runs inside the Databricks job).

    python run_pipeline.py --request /Volumes/.../training/<request_id>/request.json

Our responsibility is the MLOps integration only. The group's scripts (kit/) are called
UNMODIFIED, with their own pre/post-processing, threshold rule and evaluation code:

1. resolve the request (pipeline, exact dataset version, manifest SHA-256, parameters);
2. materialise the version in an isolated working folder (SHA-256 verified, val naming,
   repartition.csv with the bursts, no burst across splits);
3. write the effective hyperparametres.yaml;
4. ``train.py`` -- never ``--ecraser``, never ``--fusionner-test`` (independent test);
5. ``evaluer.py`` on the TEST split (validation chose the epoch and the threshold);
6. ``export_onnx.py`` when onnx / onnxruntime are installed;
7. ONE MLflow run (Ultralytics' own MLflow callback disabled), artifacts without images;
8. register a CANDIDATE version (idempotent: never twice for one run; no alias, no
   approval, no serving change). A failed registration can be retried without retraining.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT = HERE / "kit"
HP_KEYS = [
    "modele_base",
    "imgsz",
    "epochs",
    "patience",
    "batch",
    "seed",
    "erasing",
    "flipud",
    "hsv_v",
    "scale",
    "rappel_vise",
]


# --------------------------------------------------------------------------- pure helpers


def hyperparameters(params: dict[str, Any]) -> dict[str, Any]:
    """Effective hyperparametres.yaml: exactly the keys consumed by the group's train.py."""
    missing = [k for k in HP_KEYS if k not in params]
    if missing:
        raise ValueError(f"missing parameters: {missing}")
    return {k: params[k] for k in HP_KEYS}


def train_command(
    python: str, dataset: Path, out: Path, version: str, hp_file: Path, device: str
) -> list[str]:
    # No --ecraser (one output folder per run), no --fusionner-test (independent test).
    return [
        python,
        str(KIT / "train.py"),
        "--dataset",
        str(dataset),
        "--sortie",
        str(out),
        "--version",
        version,
        "--hyperparametres",
        str(hp_file),
        "--device",
        device,
    ]


def evaluate_command(python: str, config: Path, images: Path, out: Path, device: str) -> list[str]:
    return [
        python,
        str(KIT / "evaluer.py"),
        "--config",
        str(config),
        "--images",
        str(images),
        "--sortie",
        str(out),
        "--device",
        device,
        "--note",
        "split test indépendant (non utilisé pour l'époque ni le seuil)",
    ]


def export_command(python: str, config: Path, images: Path) -> list[str]:
    return [python, str(KIT / "export_onnx.py"), "--config", str(config), "--images", str(images)]


def read_results(path: Path) -> list[dict[str, float]]:
    """Ultralytics results.csv -> one dict per epoch, numeric columns only (names normalised:
    'train/loss' -> 'train_loss', 'metrics/accuracy_top1' -> 'val_accuracy_top1')."""
    if not path.is_file():
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, float] = {}
            for key, value in raw.items():
                key = key.strip()
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                name = key.replace("metrics/", "val_").replace("/", "_").replace("(B)", "")
                row[name] = number
            if "epoch" in row:
                rows.append(row)
    return rows


def training_summary(history: list[dict[str, float]], epochs_requested: int) -> dict[str, float]:
    if not history:
        return {}
    accuracy = [h.get("val_accuracy_top1", float("nan")) for h in history]
    valid = [(a, i) for i, a in enumerate(accuracy) if a == a]
    best = max(valid)[1] if valid else len(history) - 1
    return {
        "epochs_done": len(history),
        "best_epoch": int(history[best]["epoch"]),
        "early_stopped": float(len(history) < epochs_requested),
    }


def evaluation_metrics(m: dict[str, Any]) -> dict[str, float]:
    """metriques.json of evaluer.py -> MLflow metrics, prefixed with the evaluated split."""
    out = {}
    for key in (
        "rappel",
        "nok_declarees_ok",
        "faux_rejets",
        "a_verifier_ok",
        "latence_ms_moyenne",
        "latence_ms_p95",
        "seuil_nok",
    ):
        if m.get(key) is not None:
            out[f"test_{key}"] = float(m[key])
    for kind, v in (m.get("par_type") or {}).items():
        if v.get("n"):
            out[f"test_rappel_{kind}"] = v["arretees"] / v["n"]
    for key in ("n_photos", "n_nok", "n_ok"):
        if m.get(key) is not None:
            out[f"test_{key}"] = float(m[key])
    return out


def register_candidate(
    client, mlflow, registered_model: str, run_id: str, model_uri: str, tags: dict[str, str]
):
    """Idempotent: an existing version of THIS run is returned, never duplicated. Only tags
    are set: no alias, no approval tag, no serving change."""
    for v in client.search_model_versions(f"name = '{registered_model}'"):
        if v.run_id == run_id:
            return v
    version = mlflow.register_model(model_uri, registered_model)
    for key, value in tags.items():
        client.set_model_version_tag(registered_model, version.version, key, value)
    return version


def disable_ultralytics_mlflow() -> None:
    """Ultralytics has its own MLflow callback: disabled to keep ONE run per training."""
    try:
        from ultralytics import settings

        settings.update({"mlflow": False})
    except Exception:  # noqa: BLE001 - absent ultralytics fails later with a clear error
        pass


# --------------------------------------------------------------------------- orchestration


def run(request: dict[str, Any], runner=subprocess.run, mlflow=None, log=print) -> dict[str, Any]:
    import yaml

    from mlops.training.materialize import materialize

    if mlflow is None:
        import mlflow  # noqa: PLC0415
    client = mlflow.MlflowClient()
    rid, out_root = request["request_id"], Path(request["output_dir"])
    python, device = sys.executable, "cpu"
    mlflow.set_experiment(request["experiment"])
    existing = client.search_runs(
        [mlflow.get_experiment_by_name(request["experiment"]).experiment_id],
        filter_string=f"tags.`hovis.request_id` = '{rid}'",
    )
    if existing and (out_root / "test" / "metriques.json").is_file():
        # Resume: training already done for this request -> only (re)register the candidate.
        run_id = existing[0].info.run_id
        log(f"request {rid} already trained (run {run_id}): registration only")
        return {"run_id": run_id, "resumed": True}

    work = Path(request.get("work_dir") or f"/tmp/hovis/{rid}")
    data_dir = work / "dataset"
    manifest = json.loads(Path(request["manifest_path"]).read_text(encoding="utf-8"))
    t0 = time.time()
    counts = materialize(
        manifest,
        Path(request["dataset_dir"]),
        data_dir,
        {"train": "train", "validation": "val", "test": "test"},
        [".jpg"],
        group_field="group",
        group_required=True,
    )
    log(f"materialised: {counts}")
    hp = hyperparameters(request["parameters"])
    hp_file = work / "hyperparametres.yaml"
    hp_file.write_text(yaml.safe_dump(hp, sort_keys=False), encoding="utf-8")
    model_dir = out_root / "modele"
    disable_ultralytics_mlflow()
    tags = {
        "hovis.request_id": rid,
        "hovis.pipeline": request["pipeline_id"],
        "hovis.code_commit": request["code_commit"],
        "argos.dataset_id": request["dataset_id"],
        "argos.dataset_version": request["dataset_version"],
        "argos.manifest_sha256": request["manifest_sha256"],
        "hovis.fusionner_test": "false",
        "hovis.evaluation_split": "test",
        "databricks.job_id": str(request.get("job_id", "")),
        "databricks.job_run_id": str(request.get("job_run_id", "")),
    }
    for split, fp in (request.get("split_fingerprints") or {}).items():
        tags[f"hovis.split_fingerprint.{split}"] = fp
    with mlflow.start_run(run_name=f"{request['pipeline_id']}-{rid[:8]}", tags=tags) as active:
        mlflow.log_params({**hp, "device": device, "fusionner_test": False})
        steps = [("train", train_command(python, data_dir, model_dir, rid[:12], hp_file, device))]
        for name, cmd in steps:
            log(f"step {name}: {' '.join(cmd)}")
            runner(cmd, check=True, cwd=str(KIT))
        cfg_path = model_dir / "config_qualite702.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        runner(
            evaluate_command(python, cfg_path, data_dir / "test", out_root / "test", device),
            check=True,
            cwd=str(KIT),
        )
        history = read_results(model_dir / "entrainement" / "results.csv")
        for row in history:
            mlflow.log_metrics(
                {k: v for k, v in row.items() if k != "epoch"}, step=int(row["epoch"])
            )
        summary = training_summary(history, int(hp["epochs"]))
        metrics = json.loads((out_root / "test" / "metriques.json").read_text(encoding="utf-8"))
        mlflow.log_metrics(
            {
                **summary,
                **evaluation_metrics(metrics),
                "train_duration_s": time.time() - t0,
                "val_seuil_nok": float(cfg["seuil_nok"]),
            }
        )
        mlflow.set_tags(
            {f"versions.{k}": str(v) for k, v in (cfg.get("versions") or {}).items()}
            | {"python": platform.python_version()}
        )
        onnx_ok = False
        try:
            import onnx  # noqa: F401
            import onnxruntime  # noqa: F401

            runner(export_command(python, cfg_path, data_dir / "val"), check=True, cwd=str(KIT))
            onnx_ok = (model_dir / "modele.onnx").is_file()
        except Exception as exc:  # noqa: BLE001 - optional step, reported
            log(f"ONNX export skipped: {type(exc).__name__}")
        mlflow.set_tag("hovis.onnx_exported", str(onnx_ok).lower())
        for f in [
            "config_qualite702.yaml",
            "rapport_entrainement.md",
            "entrainement/results.csv",
            "rapport_export.md",
            "modele.onnx",
        ]:
            if (model_dir / f).is_file():
                mlflow.log_artifact(
                    str(model_dir / f),
                    artifact_path="training" if "/" not in f else "training/ultralytics",
                )
        for f in ["metriques.json", "predictions.csv", "rapport_evaluation.md"]:
            mlflow.log_artifact(str(out_root / "test" / f), artifact_path="evaluation")
        mlflow.log_dict({"request": request, "materialized_counts": counts}, "hovis/request.json")
        from mlops.pipelines.quality_industrial.pyfunc_model import log_quality_model

        info = log_quality_model(mlflow, model_dir, KIT)
        run_id = active.info.run_id
    version = register_candidate(
        client,
        mlflow,
        request["registered_model"],
        run_id,
        info.model_uri,
        {
            "hovis_candidate": "true",
            "argos_dataset_version": request["dataset_version"],
            "argos_dataset_id": request["dataset_id"],
            "hovis_request_id": rid,
        },
    )
    log(
        f"candidate registered: {request['registered_model']} v{version.version}"
        " (no alias, no approval)"
    )
    return {"run_id": run_id, "model_version": str(version.version), "resumed": False}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--request", required=True)
    p.add_argument("--code-root", default=str(HERE.parents[2]))
    a = p.parse_args()
    sys.path.insert(0, a.code_root)
    request = json.loads(Path(a.request).read_text(encoding="utf-8"))
    request.setdefault("job_run_id", os.environ.get("DATABRICKS_JOB_RUN_ID", ""))
    print(json.dumps(run(request)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
