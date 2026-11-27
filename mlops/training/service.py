"""Training Factory service: pipelines, catalogue of trainings, KPIs, launch, results.

Relations are EXACT: a job run <-> MLflow runs through the ``databricks.job_run_id`` tag set
by the training code; a run <-> model versions through ``version.run_id``. Never by dates or
similar names. Reads go through the connector's cache (DBX-PERF-01); details of a run are read
only when it is opened.

Remote launch / cancel / registration retry are disabled unless ``HOVIS_TRAINING_REMOTE=1``
(explicit user authorization), and use a Databricks idempotency token: a doubtful answer is
never followed by a second run.
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from mlops.databricks.connector import (
    ConflictError,
    DatabricksConnectorError,
    ForbiddenOperationError,
    ResourceNotFoundError,
)
from mlops.databricks.datasets import InvalidDatasetRequest, dataset_store
from mlops.training.checks import (
    Check,
    DatasetPreview,
    DatasetResolver,
    blocking,
    dataset_checks,
    effective_parameters,
)
from mlops.training.specs import PipelineSpec, PipelineView, load_specs, view

Status = Literal["queued", "running", "succeeded", "failed", "cancelled", "unknown"]
HOME = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))


def remote_enabled() -> bool:
    return os.environ.get("HOVIS_TRAINING_REMOTE") == "1"


def normalise(life: str | None, result: str | None) -> Status:
    if result == "SUCCESS":
        return "succeeded"
    if result in ("CANCELED", "CANCELLED"):
        return "cancelled"
    if result:
        return "failed"
    if life in ("PENDING", "QUEUED", "BLOCKED", "WAITING_FOR_RETRY"):
        return "queued"
    if life in ("RUNNING", "TERMINATING"):
        return "running"
    if life in ("INTERNAL_ERROR", "SKIPPED"):
        return "failed"
    return "unknown"


class TrainingRow(BaseModel):
    id: str
    job_run_id: int
    pipeline_id: str
    pipeline_name: str
    dataset_id: str | None
    dataset_version: str | None
    status: Status
    started_at: str | None
    ended_at: str | None
    duration_s: float | None
    mlflow_runs: list[str]
    model_versions: list[str]
    registered_model: str
    run_page_url: str | None


class Kpis(BaseModel):
    trainings_30d: int
    succeeded: int
    running: int
    failed: int
    pipelines_total: int
    pipelines_executable: int
    candidates: int
    last_training_at: str | None
    last_training_label: str | None
    unavailable: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    pipeline_id: str
    dataset: DatasetPreview | None
    parameters: dict[str, Any]
    checks: list[Check]
    launchable: bool
    compute: dict[str, Any]
    mlflow: dict[str, str]
    code: dict[str, str]
    command_preview: list[str]


class LaunchRecord(BaseModel):
    request_id: str
    idempotency_key: str
    pipeline_id: str
    dataset_id: str
    dataset_version: str
    parameters: dict[str, Any]
    status: Literal["submitted", "uncertain", "refused"]
    job_run_id: int | None = None
    created_at: str
    error: str | None = None


class LaunchStore:
    """Local record of launch requests (idempotency key -> job run)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or HOME / "training" / "launches.json"
        self.lock = threading.Lock()

    def all(self) -> dict[str, dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def get(self, key: str) -> LaunchRecord | None:
        raw = self.all().get(key)
        return LaunchRecord(**raw) if raw else None

    def put(self, record: LaunchRecord) -> None:
        with self.lock:
            data = self.all()
            data[record.idempotency_key] = record.model_dump()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class TrainingService:
    def __init__(
        self,
        connector,
        specs: list[PipelineSpec] | None = None,
        launches: LaunchStore | None = None,
    ) -> None:
        self.c = connector
        self.specs = specs if specs is not None else load_specs()
        self.launches = launches or LaunchStore()
        self.resolver = DatasetResolver(dataset_store(connector))

    # ------------------------------------------------------------------ pipelines

    def spec(self, pipeline_id: str) -> PipelineSpec:
        spec = next((s for s in self.specs if s.id == pipeline_id), None)
        if spec is None:
            raise ResourceNotFoundError(f"unknown pipeline {pipeline_id!r}")
        return spec

    def _jobs(self) -> dict[str, Any]:
        return {j.name: j for j in self.c.list_jobs()}

    def pipelines(self) -> list[PipelineView]:
        try:
            names: set[str] | None = set(self._jobs())
        except DatabricksConnectorError:
            names = None
        return [view(s, names) for s in self.specs]

    def compatible_datasets(self, pipeline_id: str) -> list[dict[str, Any]]:
        spec = self.spec(pipeline_id)
        out = []
        for fam in self.resolver.families():
            same_classes = set(fam.classes) == set(spec.classes)
            if fam.annotation_format == spec.dataset.annotation_format and (
                fam.dataset_id in spec.dataset.families or same_classes
            ):
                out.append(
                    {
                        "family": fam.model_dump(),
                        "declared": fam.dataset_id in spec.dataset.families,
                        "classes_match": same_classes,
                    }
                )
        return out

    # ------------------------------------------------------------------ validation

    def validate(
        self, pipeline_id: str, dataset_id: str, version: str, overrides: dict[str, Any]
    ) -> ValidationReport:
        spec = self.spec(pipeline_id)
        checks: list[Check] = []
        pv = next(v for v in self.pipelines() if v.spec.id == pipeline_id)
        for r in pv.requirements:
            checks.append(
                Check(
                    id=f"pipeline:{r.id}",
                    label=r.label,
                    status="ok" if r.ok else "error",
                    detail=r.detail,
                )
            )
        preview = None
        try:
            sha, manifest = self.resolver.manifest(dataset_id, version)
            preview = self.resolver.preview(dataset_id, version)
            checks += dataset_checks(spec, dataset_id, manifest)
            checks.append(
                Check(
                    id="manifest",
                    label="Manifeste publié",
                    status="ok",
                    detail=f"SHA-256 {sha[:16]}…",
                )
            )
        except (ResourceNotFoundError, InvalidDatasetRequest) as exc:
            checks.append(
                Check(id="manifest", label="Version du dataset", status="error", detail=str(exc))
            )
        params, param_checks = effective_parameters(spec, overrides)
        checks += param_checks
        if spec.evaluation.get("threshold_split"):
            checks.append(
                Check(
                    id="protocol",
                    label="Protocole d'évaluation",
                    status="ok",
                    detail="test indépendant (sans fusion) ; époque et seuil choisis sur la "
                    "validation",
                )
            )
        checks.append(
            Check(
                id="remote",
                label="Lancement distant autorisé",
                status="ok" if remote_enabled() else "error",
                detail=None
                if remote_enabled()
                else "en attente d'autorisation (aucun job ne peut être lancé)",
            )
        )
        return ValidationReport(
            pipeline_id=pipeline_id,
            dataset=preview,
            parameters=params,
            checks=checks,
            launchable=not blocking(checks),
            compute=spec.compute,
            mlflow=spec.mlflow,
            code=spec.code,
            command_preview=self._command_preview(spec, dataset_id, version),
        )

    @staticmethod
    def _command_preview(spec: PipelineSpec, dataset_id: str, version: str) -> list[str]:
        if spec.id == "quality-industrial":
            return [
                "run_pipeline.py --request <Volume>/training/<request>/request.json",
                "kit/train.py --dataset <isolé> --sortie <run>/modele --version <request>"
                " --hyperparametres <effectif> --device cpu",
                "kit/evaluer.py --config <run>/modele/config_qualite702.yaml"
                " --images <isolé>/test --sortie <run>/test",
            ]
        return [
            f"train_quality.py --dataset-dir <Volume>/{dataset_id}/{version}"
            f" (job {spec.job.get('name')})"
        ]

    # ------------------------------------------------------------------ launch / cancel

    def launch(
        self, pipeline_id: str, dataset_id: str, version: str, overrides: dict[str, Any], key: str
    ) -> LaunchRecord:
        if not key or len(key) > 64:
            raise InvalidDatasetRequest("idempotency key required (1-64 characters)")
        previous = self.launches.get(key)
        if previous and previous.status == "submitted":
            return previous  # double click / retry: same answer, no second run
        report = self.validate(pipeline_id, dataset_id, version, overrides)
        if not remote_enabled():
            raise ForbiddenOperationError("remote training launch is not authorized yet")
        if not report.launchable:
            raise ConflictError(
                "blocking checks failed: "
                + ", ".join(c.label for c in report.checks if c.status == "error")
            )
        spec = self.spec(pipeline_id)
        job = self._jobs()[spec.job["name"]]
        record = LaunchRecord(
            request_id=uuid.uuid4().hex,
            idempotency_key=key,
            pipeline_id=pipeline_id,
            dataset_id=dataset_id,
            dataset_version=version,
            parameters=report.parameters,
            status="uncertain",
            created_at=datetime.now(UTC).isoformat(),
        )
        if previous:  # earlier uncertain answer: retry with the SAME token (Databricks dedupes)
            record.request_id = previous.request_id
        self.launches.put(record)
        kwargs = self._run_arguments(spec, job.job_id, record)
        try:
            run_id = self.c._call(
                lambda: self.c.w.jobs.run_now(job.job_id, idempotency_token=key, **kwargs).run_id,
                "job",
            )
        except DatabricksConnectorError as exc:
            record.error = str(exc)
            self.launches.put(record)  # stays "uncertain": the UI must not send a NEW key
            raise
        record.status, record.job_run_id = "submitted", run_id
        self.launches.put(record)
        self.c.reads.invalidate("jobs", "jobruns:", "training:")
        return record

    def _run_arguments(
        self, spec: PipelineSpec, job_id: int, record: LaunchRecord
    ) -> dict[str, Any]:
        """quality-demo: the EXISTING job keeps its definition; only ``--dataset-dir`` is
        overridden for this run (notebook parameters). quality-industrial: a request file
        is written (never overwritten) in the reserved runs/ folder of the Volume."""
        store = dataset_store(self.c)
        if spec.job.get("dataset_argument"):
            scope = store.scope_id(record.dataset_id)
            root = store._managed(scope).dataset_root
            full = self.c._call(lambda: self.c.w.jobs.get(job_id), "job")
            task = full.settings.tasks[0]
            args = json.loads(task.notebook_task.base_parameters["args"])
            flag = spec.job["dataset_argument"]
            args[args.index(flag) + 1] = f"{root}/{record.dataset_version}"
            return {
                "notebook_params": {**task.notebook_task.base_parameters, "args": json.dumps(args)}
            }
        sha, _ = self.resolver.manifest(record.dataset_id, record.dataset_version)
        scope = store.scope_id(record.dataset_id)
        dataset_dir = f"{store._managed(scope).dataset_root}/{record.dataset_version}"
        base = f"{store.catalog_root.rsplit('/', 1)[0]}/runs/hovis/{record.request_id}"
        summary = self.resolver.summary(record.dataset_id, record.dataset_version)
        request = {
            "request_id": record.request_id,
            "pipeline_id": spec.id,
            "dataset_id": record.dataset_id,
            "dataset_version": record.dataset_version,
            "manifest_sha256": sha,
            "manifest_path": f"{dataset_dir}/manifest.json",
            "dataset_dir": dataset_dir,
            "parameters": record.parameters,
            "experiment": spec.mlflow["experiment"],
            "registered_model": spec.mlflow["registered_model"],
            "code_commit": spec.code.get("commit", ""),
            "output_dir": f"{base}/outputs",
            "split_fingerprints": summary.split_fingerprints if summary else {},
        }
        store._upload(f"{base}/request.json", json.dumps(request, indent=2).encode())
        return {"job_parameters": {"request": f"{base}/request.json"}}

    def cancel(self, job_run_id: int) -> None:
        if not remote_enabled():
            raise ForbiddenOperationError("remote job cancellation is not authorized yet")
        self.c._call(lambda: self.c.w.jobs.cancel_run(job_run_id), "job run")
        self.c.reads.invalidate("jobruns:", "training:")

    # ------------------------------------------------------------------ catalogue

    def _mlflow_runs(self, spec: PipelineSpec) -> list[Any]:
        exp = self.c._cached(
            f"training:exp:{spec.id}",
            lambda: self.c.mlflow.get_experiment_by_name(spec.mlflow["experiment"]),
        )
        if exp is None:
            return []
        return self.c._cached(
            f"training:mlruns:{spec.id}",
            lambda: self.c.mlflow.search_runs([exp.experiment_id], max_results=200),
        )

    def _versions(self, spec: PipelineSpec) -> list[Any]:
        name = spec.mlflow["registered_model"]
        try:
            return self.c._cached(
                f"training:versions:{spec.id}",
                lambda: list(self.c.mlflow.search_model_versions(f"name = '{name}'")),
            )
        except DatabricksConnectorError:
            return []

    def trainings(self) -> list[TrainingRow]:
        return self.c._cached("training:rows", self._trainings)

    def _trainings(self) -> list[TrainingRow]:
        jobs = self._jobs()
        launches = {r["job_run_id"]: r for r in self.launches.all().values() if r.get("job_run_id")}
        rows = []
        for spec in self.specs:
            job = jobs.get(spec.job.get("name"))
            if job is None:
                continue
            mlruns = self._mlflow_runs(spec)
            versions = self._versions(spec)
            for jr in self.c.job_runs(job.job_id, 25):  # Databricks API maximum
                linked = [
                    r
                    for r in mlruns
                    if (r.data.tags or {}).get("databricks.job_run_id") == str(jr.run_id)
                ]
                run_ids = [r.info.run_id for r in linked]
                params = linked[0].data.params if linked else {}
                tags = linked[0].data.tags if linked else {}
                launch = launches.get(jr.run_id, {})
                rows.append(
                    TrainingRow(
                        id=f"TR-{jr.run_id}",
                        job_run_id=jr.run_id,
                        pipeline_id=spec.id,
                        pipeline_name=spec.name,
                        dataset_id=tags.get("argos.dataset_id")
                        or launch.get("dataset_id")
                        or (spec.dataset.families[0] if linked else None),
                        dataset_version=params.get("dataset_version")
                        or tags.get("argos.dataset_version")
                        or launch.get("dataset_version"),
                        status=normalise(jr.life_cycle_state, jr.result_state),
                        started_at=jr.start_time.isoformat() if jr.start_time else None,
                        ended_at=jr.end_time.isoformat() if jr.end_time else None,
                        duration_s=jr.duration_s,
                        mlflow_runs=run_ids,
                        model_versions=sorted(
                            {str(v.version) for v in versions if v.run_id in run_ids}, key=int
                        ),
                        registered_model=spec.mlflow["registered_model"],
                        run_page_url=jr.run_page_url,
                    )
                )
        rows.sort(key=lambda r: r.started_at or "", reverse=True)
        return rows

    def kpis(self) -> Kpis:
        rows = self.trainings()
        since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        recent = [r for r in rows if (r.started_at or "") >= since]
        views = self.pipelines()
        candidates = sum(len(self._versions(s)) for s in self.specs)
        last = rows[0] if rows else None
        return Kpis(
            trainings_30d=len(recent),
            succeeded=sum(r.status == "succeeded" for r in recent),
            running=sum(r.status in ("running", "queued") for r in rows),
            failed=sum(r.status == "failed" for r in recent),
            pipelines_total=len(views),
            pipelines_executable=sum(v.executable for v in views),
            candidates=candidates,
            last_training_at=last.started_at if last else None,
            last_training_label=f"{last.pipeline_id} · {last.dataset_version or 'dataset inconnu'}"
            if last
            else None,
        )

    def row(self, job_run_id: int) -> TrainingRow:
        found = next((r for r in self.trainings() if r.job_run_id == job_run_id), None)
        if found is None:
            raise ResourceNotFoundError(f"training {job_run_id} not found")
        return found

    # ------------------------------------------------------------------ results

    def detail(self, job_run_id: int) -> dict[str, Any]:
        row = self.row(job_run_id)
        spec = self.spec(row.pipeline_id)
        runs = [self.c.get_run(r) for r in row.mlflow_runs]
        return {
            "row": row.model_dump(),
            "pipeline": spec.model_dump(),
            "runs": [r.model_dump() for r in runs],
        }

    def history(self, run_id: str) -> dict[str, list[dict[str, float]]]:
        run = self.c.get_run(run_id)
        keys = [k for k in run.metrics if any(t in k for t in ("loss", "accuracy"))]
        return {k: [p.model_dump() for p in self.c.metric_history(run_id, k)] for k in keys}

    def _artifact(self, run_id: str, path: str) -> bytes | None:
        cache = HOME / "cache" / "artifacts" / run_id / path
        if cache.is_file():
            return cache.read_bytes()
        if path not in self._folder(run_id, path.rsplit("/", 1)[0] if "/" in path else None):
            return None  # folder listed once (cached): no slow download attempt for an absent file
        try:
            local = self.c._call(
                lambda: self.c.mlflow.download_artifacts(run_id, path, str(cache.parent.parent)),
                "artifact",
            )
        except ResourceNotFoundError:
            return None
        except DatabricksConnectorError as exc:
            if "Failed to download artifacts" in str(exc) or "does not exist" in str(exc):
                return None  # absent artefact = "unavailable", not an error
            raise
        data = Path(local).read_bytes()
        cache.parent.mkdir(parents=True, exist_ok=True)
        if Path(local) != cache:
            cache.write_bytes(data)
        return data

    def evaluation(self, run_id: str) -> dict[str, Any]:
        raw = self._artifact(run_id, "evaluation/metriques.json")
        preds = self._artifact(run_id, "evaluation/predictions.csv")
        if raw is None or preds is None:
            own = self._artifact(run_id, "reports/confusion_matrix_test.json")
            if own is not None:  # pipeline's own test confusion matrix (quality-demo / DBX-00)
                matrix = from_matrix(json.loads(own))
                return {
                    "available": True,
                    "source": "reports/confusion_matrix_test.json",
                    "metrics": {},
                    **matrix,
                }
            return {
                "available": False,
                "reason": "no evaluation artefacts (metriques.json / predictions.csv) for this run",
            }
        rows = list(csv.DictReader(io.StringIO(preds.decode("utf-8"))))
        return {"available": True, "split": "test", "metrics": json.loads(raw), **confusion(rows)}

    def predictions(
        self,
        run_id: str,
        dataset_id: str | None,
        version: str | None,
        f: dict[str, str],
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        preds = self._artifact(run_id, "evaluation/predictions.csv")
        if preds is None:
            return {"available": False, "total": 0, "items": []}
        rows = [enrich(r) for r in csv.DictReader(io.StringIO(preds.decode("utf-8")))]
        files: dict[tuple[str, str], str] = {}
        if dataset_id and version:
            _, m = self.resolver.manifest(dataset_id, version)
            index: dict[tuple[str, str], list[str]] = {}
            for item in m["items"]:
                if item["split"] == "test":
                    index.setdefault((item["label"], Path(item["file"]).name), []).append(
                        item["file"]
                    )
            files = {
                k: v[0] for k, v in index.items() if len(v) == 1
            }  # ambiguous names are not linked
        selected = [r for r in rows if match(r, f)]
        page = selected[offset : offset + limit]
        for r in page:
            r["manifest_file"] = files.get((r["vraie_classe"], r["fichier"]))
        return {
            "available": True,
            "total": len(selected),
            "offset": offset,
            "limit": limit,
            "items": page,
            "dataset_id": dataset_id,
            "version": version,
        }

    def _folder(self, run_id: str, folder: str | None) -> set[str]:
        """Paths of ONE artefact folder (shallow listing, cached 1 h)."""

        def listing() -> set[str]:
            return {
                a.path
                for a in self.c._call(
                    lambda: self.c.mlflow.list_artifacts(run_id, folder), "artifacts"
                )
            }

        return self.c._cached(f"training:artdir:{run_id}:{folder}", listing, ttl=3600)

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return self.c._cached(
            f"training:artlist:{run_id}", lambda: self._artifacts(run_id), ttl=3600
        )

    def _artifacts(self, run_id: str) -> list[dict[str, Any]]:
        out, stack = [], [None]
        while stack and len(out) < 200:
            path = stack.pop()
            for a in self.c._call(
                lambda p=path: self.c.mlflow.list_artifacts(run_id, p), "artifacts"
            ):
                if a.is_dir:
                    stack.append(a.path)
                else:
                    out.append({"path": a.path, "size": a.file_size})
        return sorted(out, key=lambda a: a["path"])

    def logs(self, job_run_id: int) -> dict[str, Any]:
        run = self.c._call(lambda: self.c.w.jobs.get_run(job_run_id), "job run")
        tasks = []
        for t in run.tasks or []:
            try:
                o = self.c._call(
                    lambda tid=t.run_id: self.c.w.jobs.get_run_output(tid), "run output"
                )
                tasks.append(
                    {
                        "task": t.task_key,
                        "error": o.error,
                        "logs": (o.logs or "")[-20000:],
                        "notebook_output": getattr(o.notebook_output, "result", None),
                    }
                )
            except DatabricksConnectorError as exc:
                tasks.append({"task": t.task_key, "error": str(exc), "logs": None})
        return {
            "run_page_url": run.run_page_url,
            "state": run.state.state_message if run.state else None,
            "tasks": tasks,
        }


# --------------------------------------------------------------------------- evaluation helpers


def decision(r: dict[str, str]) -> str:
    """Column of the group's confusion matrix: OK / A_VERIFIER / predicted NOK type."""
    return r["verdict"] if r["verdict"] in ("OK", "A_VERIFIER") else (r.get("type_defaut") or "NOK")


def enrich(r: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = dict(r)
    truth_nok = r["vraie_classe"] != "OK"
    d = decision(r)
    out["decision"] = d
    out["score_nok"] = float(r["score_nok"]) if r.get("score_nok") else None
    out["latence_ms"] = float(r["latence_ms"]) if r.get("latence_ms") else None
    out["false_reject"] = not truth_nok and r["verdict"] == "NOK"
    out["missed_defect"] = truth_nok and r["verdict"] == "OK"
    out["type_confusion"] = truth_nok and r["verdict"] == "NOK" and d != r["vraie_classe"]
    out["to_check"] = r["verdict"] == "A_VERIFIER"
    out["correct"] = d == r["vraie_classe"]
    return out


KINDS = ("correct", "incorrect", "false_reject", "missed_defect", "type_confusion", "to_check")


def match(r: dict[str, Any], f: dict[str, str]) -> bool:
    if f.get("true") and r["vraie_classe"] != f["true"]:
        return False
    if f.get("pred") and r["decision"] != f["pred"]:
        return False
    kind = f.get("kind")
    if not kind:
        return True
    if kind == "incorrect":
        return not r["correct"]
    return bool(r.get(kind))


def confusion(rows: list[dict[str, str]]) -> dict[str, Any]:
    truths = sorted({r["vraie_classe"] for r in rows}, key=lambda c: (c != "OK", c))
    cols = ["OK", "A_VERIFIER"] + [c for c in truths if c != "OK"]
    counts = {t: {c: 0 for c in cols} for t in truths}
    for r in rows:
        d = decision(r)
        counts[r["vraie_classe"]].setdefault(d, 0)
        counts[r["vraie_classe"]][d] += 1
    per_class = {}
    for c in truths:
        tp = counts[c].get(c, 0)
        support = sum(counts[c].values())
        predicted = sum(counts[t].get(c, 0) for t in truths)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
        per_class[c] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    return {
        "truth_classes": truths,
        "columns": cols,
        "matrix": counts,
        "per_class": per_class,
        "n": len(rows),
    }


def from_matrix(data: dict[str, Any]) -> dict[str, Any]:
    """{labels, matrix, split} written by a pipeline -> same shape as ``confusion``."""
    labels = list(data["labels"])
    counts = {
        t: {c: int(data["matrix"][i][j]) for j, c in enumerate(labels)}
        for i, t in enumerate(labels)
    }
    per_class = {}
    for c in labels:
        tp, support = counts[c][c], sum(counts[c].values())
        predicted = sum(counts[t][c] for t in labels)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
        per_class[c] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    n = sum(sum(r.values()) for r in counts.values())
    split = data.get("split", "test")
    return {
        "split": split,
        "truth_classes": labels,
        "columns": labels,
        "matrix": counts,
        "per_class": per_class,
        "n": n,
    }
