"""Run the Workstation group's unchanged statistical evaluation in an isolated job.

The published dataset must contain the group's original photos, labels.csv and reference.
This adapter only verifies/copies them, calls the group's evaluate() and records its results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(globals().get("__file__") or sys.argv[0]).resolve().parent
KIT = HERE / "kit"
SECTIONS = {
    "press_cell": ("poste-5s-11", "poste_5s_11"),
    "machine_cell": ("poste-bleu-5s-11", "poste_bleu_5s_11"),
    "machine_cell_variant": ("poste-variante-5s-11", "poste_variante_5s_11"),
    "electrical_bench": ("poste-electrique-5s-11", "poste_electrique_5s_11"),
}


def digest(path: Path) -> str:
    hash_ = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_.update(block)
    return hash_.hexdigest()


def safe_file(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(p in ("", ".", "..") for p in path.parts)
    ):
        raise ValueError(f"unsafe dataset path: {name}")
    return path


def materialize(manifest: dict, source: Path, target: Path, section: str) -> dict[str, int]:
    """Copy one verified file at a time into the layout expected by the group's station YAML."""
    family, folder = SECTIONS[section]
    if manifest.get("dataset_id") != family or manifest.get("station") != section:
        raise ValueError("dataset family/section mismatch")
    if set(manifest.get("classes", [])) != {"good", "anomaly"}:
        raise ValueError("expected original good/anomaly labels")
    entries = [*manifest.get("items", []), *manifest.get("assets", [])]
    names: set[str] = set()
    labels = Counter()
    for entry in entries:
        rel = safe_file(entry["file"])
        if rel.parts[:3] != ("raw", "workstation", folder):
            raise ValueError(f"file outside selected section: {rel}")
        if str(rel) in names:
            raise ValueError(f"duplicate file: {rel}")
        names.add(str(rel))
        src, dst = source / Path(*rel.parts), target / Path(*rel.parts)
        if not src.is_file() or digest(src) != entry["sha256"]:
            raise ValueError(f"missing or changed workstation file: {rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            if digest(dst) != entry["sha256"]:
                raise ValueError(f"changed local workstation copy: {rel}")
        else:
            shutil.copy2(src, dst)
        if entry in manifest.get("items", []):
            labels[entry["label"]] += 1
    required = {f"raw/workstation/{folder}/reference.png", f"raw/workstation/{folder}/labels.csv"}
    if not required.issubset(names) or not labels["good"] or not labels["anomaly"]:
        raise ValueError("reference, labels.csv and both labelled classes are required")
    return dict(labels)


def metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    anomalies = [r for r in rows if r["expected"] == "anomalie"]
    goods = [r for r in rows if r["expected"] == "conforme"]
    if not anomalies or not goods:
        raise ValueError("evaluation requires good and anomalous images")

    def flagged(row: dict[str, Any]) -> bool:
        return row["decision"] != "conforme"

    latencies = sorted(float(r["latency_ms"]) for r in rows)
    return {
        "cv_images": float(len(rows)),
        "cv_anomaly_recall": sum(map(flagged, anomalies)) / len(anomalies),
        "cv_right_reason_recall": sum(bool(r["right_reason"]) for r in anomalies) / len(anomalies),
        "cv_false_alarm_rate": sum(map(flagged, goods)) / len(goods),
        "cv_alignment_failures": float(sum(bool(r["alignment_failed"]) for r in rows)),
        "cv_latency_mean_ms": sum(latencies) / len(latencies),
        "cv_latency_p95_ms": latencies[int(0.95 * (len(latencies) - 1))],
    }


def run(request: dict[str, Any], *, repo_root: Path | None = None) -> dict[str, Any]:
    """A remote launch is gated by TrainingService; this function never invents results."""
    import cv2
    import mlflow

    from mlops.pipelines.quality_industrial.run_pipeline import register_candidate
    from mlops.pipelines.workstation.pyfunc_model import log_workstation_model

    repo_root = repo_root or HERE.parents[2]
    section = request["parameters"]["station"]
    if section not in SECTIONS or request["dataset_id"] != SECTIONS[section][0]:
        raise ValueError("request does not match a Workstation section")
    published = Path(request["output_dir"])
    result_file = published / "result.json"
    if result_file.is_file():
        return json.loads(result_file.read_text(encoding="utf-8"))
    if request.get("registry_uri"):
        mlflow.set_registry_uri(request["registry_uri"])
    mlflow.set_experiment(request["experiment"])
    client = mlflow.MlflowClient()
    experiment = mlflow.get_experiment_by_name(request["experiment"])
    existing = client.search_runs(
        [experiment.experiment_id],
        filter_string=f"tags.`hovis.request_id` = '{request['request_id']}'",
    )
    if existing and existing[0].info.status == "FINISHED":
        run_id = existing[0].info.run_id
        version = register_candidate(
            client,
            mlflow,
            request["registered_model"],
            run_id,
            f"runs:/{run_id}/model",
            {
                "hovis_candidate": "true",
                "argos_dataset_id": request["dataset_id"],
                "argos_dataset_version": request["dataset_version"],
            },
        )
        result = {"run_id": run_id, "model_version": str(version.version), "resumed": True}
        published.mkdir(parents=True, exist_ok=True)
        result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    manifest_path = Path(request["manifest_path"])
    if digest(manifest_path) != request["manifest_sha256"]:
        raise ValueError("manifest SHA-256 mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    work = Path(request.get("work_dir") or f"/tmp/hovis/{request['request_id']}")
    data_root, out = work / "dataset", work / "outputs"
    counts = materialize(manifest, Path(request["dataset_dir"]), data_root, section)
    weights_source = Path(request.get("base_weights") or "")
    if not weights_source.is_file() or weights_source.stat().st_size == 0:
        raise FileNotFoundError("public YOLO26 COCO weights are not staged in the Volume")
    weights = work / "weights" / "yolo26n.pt"
    weights.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(weights_source, weights)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    sys.path.insert(0, str(KIT))
    from usecases.workstation import evaluate as group_eval
    from usecases.workstation.station import load_station
    from visionhub.config import load_use_case_config

    # The original evaluator imports this function directly. Only its config location is
    # adapted; scientific methods and thresholds remain the group's own files.
    group_eval.load_use_case_config = lambda use_case: load_use_case_config(
        use_case, base_dir=KIT / "usecases"
    )
    station = load_station(section, data_root)
    annotated = out / "annotated"
    start = time.perf_counter()
    rows, analyzer = group_eval.evaluate(
        station,
        {"detector": "coco", "device": "cpu", "weights": str(weights)},
        folds=5,
        slots=True,
        annotate_dir=annotated,
    )
    elapsed = time.perf_counter() - start
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.txt").write_text(group_eval.summary(rows) + "\n", encoding="utf-8")
    for view in analyzer.views:
        cv2.imwrite(
            str(out / f"preview_{view.name}.png"), group_eval.draw_regions(view.image, view)
        )
    measured = metrics(rows) | {"duration_evaluate_s": elapsed}
    (out / "evaluation.json").write_text(json.dumps(measured, indent=2), encoding="utf-8")
    with mlflow.start_run(
        run_name=f"workstation-{section}-{request['request_id'][:8]}",
        tags={
            "hovis.request_id": request["request_id"],
            "hovis.pipeline": request["pipeline_id"],
            "argos.dataset_id": request["dataset_id"],
            "argos.dataset_version": request["dataset_version"],
            "argos.manifest_sha256": request["manifest_sha256"],
            "hovis.scientific_method": "group-statistical-normality-cv",
            "databricks.job_run_id": str(request.get("job_run_id", "")),
        },
    ) as active:
        mlflow.log_params(
            {**request["parameters"], "section": section, "weights_sha256": digest(weights)}
        )
        mlflow.log_metrics(measured)
        mlflow.log_artifacts(str(out), artifact_path="evaluation")
        mlflow.log_dict({"source_counts": counts, "request": request}, "hovis/request.json")
        model = log_workstation_model(mlflow, section, data_root, weights, KIT, repo_root, work)
        run_id = active.info.run_id
    published.mkdir(parents=True, exist_ok=True)
    shutil.copytree(out, published, dirs_exist_ok=True)
    version = register_candidate(
        client,
        mlflow,
        request["registered_model"],
        run_id,
        model.model_uri,
        {
            "hovis_candidate": "true",
            "argos_dataset_id": request["dataset_id"],
            "argos_dataset_version": request["dataset_version"],
        },
    )
    result = {"run_id": run_id, "model_version": str(version.version), "metrics": measured}
    result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--code-root", default=str(HERE.parents[2]))
    parser.add_argument("--job-id", default="")
    parser.add_argument("--job-run-id", default="")
    args = parser.parse_args()
    sys.path.insert(0, args.code_root)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    request["job_run_id"] = "" if "{{" in args.job_run_id else args.job_run_id
    print("HOVIS_RESULT=" + json.dumps(run(request, repo_root=Path(args.code_root))))
    return 0


if __name__ == "__main__":
    main()
