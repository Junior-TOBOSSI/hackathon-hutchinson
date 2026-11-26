"""DBX-00I: TEMPORARY local FastAPI showing that a React frontend can drive Databricks
without ever seeing a secret (credentials stay in the CLI profile of this process).

    python -m uvicorn mlops.databricks_poc.api:app --host 127.0.0.1 --port 8030
    (run with the ARGOS MLOps venv python)

These endpoints are POC endpoints, NOT the final integration contracts.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from mlops.databricks_poc.common import (
    ENDPOINT,
    EXPERIMENT,
    LOCAL_DATASET,
    MODEL,
    RESULTS,
    remaining_inferences,
    workspace_client,
)
from mlops.databricks_poc.inference import RemoteModel, sample_images
from visionhub.config import load_use_case_config
from visionhub.contracts import UseCase
from visionhub.decision import decide
from visionhub.production.verdicts import verdict_from_decision

app = FastAPI(title="ARGOS DBX-00 POC API", version="0.0.1")


@lru_cache(maxsize=1)
def client():
    return workspace_client()


def mlflow_client():
    import mlflow

    client()  # process environment: profile, MLflow URIs
    return mlflow.MlflowClient(tracking_uri="databricks", registry_uri="databricks-uc")


class InferenceRequest(BaseModel):
    image_base64: str | None = Field(default=None, description="PNG/JPEG in base64")
    sample: str | None = Field(
        default=None, pattern="^(OK|NOK)$", description="or a synthetic test image"
    )


@app.get("/health")
def health() -> dict:
    w = client()
    endpoint = w.serving_endpoints.get(ENDPOINT)
    return {
        "status": "ok",
        "databricks_user_active": bool(w.current_user.me().active),
        "endpoint": ENDPOINT,
        "endpoint_ready": endpoint.state.ready.value if endpoint.state else None,
        "remote_inferences_left": remaining_inferences(),
    }


@app.get("/poc/experiments")
def experiments() -> dict:
    mlflow = mlflow_client()
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        raise HTTPException(404, f"experiment {EXPERIMENT} not found")
    runs = mlflow.search_runs([experiment.experiment_id], max_results=20)
    return {
        "experiment_id": experiment.experiment_id,
        "name": experiment.name,
        "runs": [
            {
                "run_id": r.info.run_id,
                "run_name": r.info.run_name,
                "status": r.info.status,
                "metrics": r.data.metrics,
                "role": r.data.tags.get("argos.selection_role"),
                "job_run_id": r.data.tags.get("databricks.job_run_id"),
            }
            for r in runs
        ],
    }


@app.get("/poc/models")
def models() -> dict:
    mlflow = mlflow_client()
    model = mlflow.get_registered_model(MODEL)
    # Unity Catalog search results do not carry tags: read each version individually.
    numbers = sorted(int(v.version) for v in mlflow.search_model_versions(f"name = '{MODEL}'"))
    versions = [mlflow.get_model_version(MODEL, str(n)) for n in numbers]
    return {
        "name": MODEL,
        "aliases": dict(model.aliases or {}),
        "versions": [
            {
                "version": v.version,
                "run_id": v.run_id,
                "status": v.status,
                "tags": dict(v.tags or {}),
            }
            for v in versions
        ],
    }


@app.get("/poc/jobs")
def jobs() -> list[dict]:
    w = client()
    out = []
    for job in w.jobs.list(name=None):
        if not (job.settings and (job.settings.name or "").startswith("argos-poc")):
            continue
        last = next(iter(w.jobs.list_runs(job_id=job.job_id, limit=1)), None)
        out.append(
            {
                "job_id": job.job_id,
                "name": job.settings.name,
                "last_run": None
                if last is None
                else {
                    "run_id": last.run_id,
                    "state": last.state.life_cycle_state.value,
                    "result": last.state.result_state.value if last.state.result_state else None,
                },
            }
        )
    return out


@app.post("/poc/inference")
def inference(request: InferenceRequest) -> dict:
    if request.image_base64:
        image = request.image_base64
        truth = None
    elif request.sample:
        item = next(i for i in sample_images(2) if i["label"] == request.sample)
        image = base64.b64encode((LOCAL_DATASET / item["file"]).read_bytes()).decode()
        truth = item["label"]
    else:
        raise HTTPException(422, "give image_base64 or sample")
    if remaining_inferences() < 1:
        raise HTTPException(429, "POC remote inference budget exhausted")
    remote = RemoteModel(client())
    result = remote.predict(image, "fastapi /poc/inference")
    if result["http_status"] != 200 or not result["prediction"]:
        # Never a silent "OK": the ARGOS verdict of a failed inference is ERROR.
        return {"verdict": "ERROR", "error": result["error"], "http_status": result["http_status"]}
    score = float(result["prediction"]["anomaly_score"])
    decision = decide(score, load_use_case_config(UseCase.QUALITY).thresholds)
    return {
        "served_model": MODEL,
        "served_version": remote.served_version(),
        "prediction": result["prediction"],
        "argos_decision": decision.value,
        "argos_verdict": verdict_from_decision(decision).value,
        "latency_ms": result["latency_ms"],
        "ground_truth": truth,
        "remote_inferences_left": remaining_inferences(),
    }


@app.get("/poc/monitoring")
def monitoring() -> dict:
    """Last drift report read from Delta through the SQL warehouse (cached locally so that
    this demo endpoint never starts a warehouse by itself)."""
    path = RESULTS / "drift_report.json"
    if not path.exists():
        raise HTTPException(404, "no drift report yet (run monitoring report)")
    data = json.loads(path.read_text(encoding="utf-8"))
    columns = [
        "feature",
        "method",
        "value",
        "threshold",
        "alert",
        "reference_mean",
        "current_mean",
        "n_reference",
        "n_current",
    ]
    return {
        "source": "Delta table workspace.argos_poc.drift_report (read via SQL warehouse)",
        "read_at": data["recorded_at"],
        "rows": [dict(zip(columns, row, strict=False)) for row in data["rows"]],
    }
