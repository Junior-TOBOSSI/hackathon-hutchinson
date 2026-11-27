"""DBX-00E/F: remote inference on the serving endpoint and local inference of the same version.

    python -m mlops.databricks_poc.inference remote --count 6      # consumes the budget (max 20)
    python -m mlops.databricks_poc.inference local --version 1     # no remote call

Remote calls go through HTTPS with the OAuth headers of the CLI profile (never printed).
Each call sends ONE image, so 1 call = 1 inference of the POC budget.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time

import requests

from mlops.databricks_poc.common import (
    ENDPOINT,
    LOCAL_DATASET,
    MODEL,
    consume_inference_budget,
    remaining_inferences,
    save_result,
    workspace_client,
)

TIMEOUT_S = 120


def sample_images(count: int, split: str = "test") -> list[dict]:
    """Alternate OK / NOK images of the split, deterministic order."""
    manifest = json.loads((LOCAL_DATASET / "manifest.json").read_text(encoding="utf-8"))
    by_label = {
        label: [i for i in manifest["items"] if i["split"] == split and i["label"] == label]
        for label in ("OK", "NOK")
    }
    chosen = []
    for index in range(count):
        label = ("OK", "NOK")[index % 2]
        chosen.append(by_label[label][index // 2])
    return chosen


def encode(file: str) -> str:
    return base64.b64encode((LOCAL_DATASET / file).read_bytes()).decode()


class RemoteModel:
    """Thin HTTPS client of the serving endpoint (the shape a FastAPI service would use)."""

    def __init__(self, w=None) -> None:
        self.w = w or workspace_client()
        self.url = f"{self.w.config.host.rstrip('/')}/serving-endpoints/{ENDPOINT}/invocations"

    def served_version(self) -> str | None:
        endpoint = self.w.serving_endpoints.get(ENDPOINT)
        entities = endpoint.config.served_entities if endpoint.config else []
        return entities[0].entity_version if entities else None

    def predict(self, image_base64: str, purpose: str) -> dict:
        consume_inference_budget(1, purpose)
        headers = {"Content-Type": "application/json", **self.w.config.authenticate()}
        start = time.perf_counter()
        response = requests.post(
            self.url,
            headers=headers,
            json={"dataframe_records": [{"image_base64": image_base64}]},
            timeout=TIMEOUT_S,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        prediction = (body.get("predictions") or [None])[0]
        return {
            "http_status": response.status_code,
            "latency_ms": round(latency_ms, 1),
            "prediction": prediction,
            "error": None if response.ok else response.text[:300],
        }


def load_local(version: str):
    import mlflow

    mlflow.set_registry_uri("databricks-uc")
    return mlflow.pyfunc.load_model(f"models:/{MODEL}/{version}")


def run_remote(count: int) -> int:
    if count > remaining_inferences():
        print(f"refused: {count} requested, {remaining_inferences()} remaining in the POC budget")
        return 1
    remote = RemoteModel()
    version = remote.served_version()
    calls = []
    for item in sample_images(count):
        result = remote.predict(encode(item["file"]), f"remote test v{version}")
        calls.append({"file": item["file"], "label": item["label"], **result})
        print(
            f"  {item['file']:<28} truth={item['label']:<3} HTTP {result['http_status']} "
            f"{result['latency_ms']:>8.1f} ms -> {result['prediction'] or result['error']}"
        )
    path = save_result(
        f"remote_inference_v{version}_{int(time.time())}",
        {"served_version": version, "calls": calls},
    )
    print(f"served version {version}; budget remaining {remaining_inferences()}; saved to {path}")
    return 0 if all(c["http_status"] == 200 for c in calls) else 1


def run_local(version: str, compare_with: str | None) -> int:
    import pandas as pd

    model = load_local(version)
    print(f"loaded models:/{MODEL}/{version} locally ({type(model).__name__})")
    calls = (
        json.loads(open(compare_with, encoding="utf-8").read())["calls"] if compare_with else None
    )
    items = [{"file": c["file"], "label": c["label"]} for c in calls] if calls else sample_images(6)
    frame = pd.DataFrame({"image_base64": [encode(i["file"]) for i in items]})
    start = time.perf_counter()
    predictions = model.predict(frame)
    latency_ms = (time.perf_counter() - start) * 1000
    rows = []
    for index, item in enumerate(items):
        local = {
            "class": predictions["class"].iloc[index],
            "anomaly_score": float(predictions["anomaly_score"].iloc[index]),
        }
        row = {"file": item["file"], "label": item["label"], "local": local}
        if calls:
            remote = calls[index]["prediction"]
            row["remote"] = remote
            row["same_class"] = remote["class"] == local["class"]
            row["score_abs_diff"] = abs(remote["anomaly_score"] - local["anomaly_score"])
        rows.append(row)
        print(
            f"  {item['file']:<28} truth={item['label']:<3} local={local}"
            + (f" remote={row['remote']} diff={row['score_abs_diff']:.2e}" if calls else "")
        )
    summary = {"version": version, "batch_latency_ms": round(latency_ms, 1), "rows": rows}
    if calls:
        summary["all_classes_match"] = all(r["same_class"] for r in rows)
        summary["max_score_abs_diff"] = max(r["score_abs_diff"] for r in rows)
        print(
            f"classes match: {summary['all_classes_match']}; "
            f"max |score diff| = {summary['max_score_abs_diff']:.2e}"
        )
    path = save_result(f"local_inference_v{version}", summary)
    print(f"saved to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    remote = sub.add_parser("remote")
    remote.add_argument("--count", type=int, default=6)
    local = sub.add_parser("local")
    local.add_argument("--version", required=True)
    local.add_argument("--compare-with", help="JSON result of a remote run (same images)")
    args = parser.parse_args(argv)
    workspace_client()  # sets the process environment (profile, MLflow URIs, CLI path)
    return (
        run_remote(args.count)
        if args.mode == "remote"
        else run_local(args.version, args.compare_with)
    )


if __name__ == "__main__":
    sys.exit(main())
