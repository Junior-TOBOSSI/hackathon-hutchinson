"""DBX-00G: minimal industrial simulation calling the REAL Databricks endpoint.

    python -m mlops.databricks_poc.simulator --cycles 4
    python -m mlops.databricks_poc.simulator --cycles 4 --drift

What is simulated and what is real:
  SIMULATED : the machine (station id, cycle id), the images (synthetic squares), the drift
  REAL      : the HTTPS call, the model inference on Databricks, the latency, the score

The anomaly score of the served model goes through the UNCHANGED ARGOS decision layer
(``visionhub.decision.to_event`` with the thresholds of ``usecases/quality/config.yaml``),
then to the Production Engine verdict mapping. A network error or timeout gives ERROR,
never OK. Results are appended to a local telemetry file (then pushed to Delta by
``monitoring.py``).

Adapter still needed for the Production Engine (not built here, shared code untouched):
an ``Analyzer`` subclass (``use_case = QUALITY``) whose ``analyze()`` encodes the image,
calls the endpoint and returns ``AnalysisResult(score=anomaly_score, model_name=MODEL,
model_version=<served version>, details=QualityDetails())``, raising on HTTP errors so that
``ProductionEngine`` records ``ERROR`` parts. It plugs in through ``usecases/quality/config.yaml``.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import uuid
from datetime import UTC, datetime

import numpy as np
from PIL import Image

from mlops.databricks_poc.common import LOCAL_HOME, MODEL, remaining_inferences, save_result
from mlops.databricks_poc.dataset import render
from mlops.databricks_poc.inference import RemoteModel, sample_images
from visionhub.config import load_use_case_config
from visionhub.contracts import AnalysisResult, FrameMeta, QualityDetails, UseCase
from visionhub.decision import to_event
from visionhub.integration.edge_events import EdgeEvent, InferencePayload
from visionhub.production.contracts import PartVerdict
from visionhub.production.verdicts import verdict_from_decision

TELEMETRY = LOCAL_HOME / "telemetry.jsonl"
DRIFT_SEED = 7_777


def image_stats(png: bytes) -> dict:
    """Brightness (mean/255) and blur (variance of a 4-neighbour Laplacian; low = blurry)."""
    pixels = np.asarray(Image.open(io.BytesIO(png)).convert("L"), dtype=np.float32)
    laplacian = (
        -4 * pixels[1:-1, 1:-1]
        + pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
    )
    return {"brightness": float(pixels.mean() / 255), "blur": float(laplacian.var())}


def drifted_image(label: str, rng: np.random.Generator) -> bytes:
    """Synthetic image with a SIMULATED acquisition drift: brighter scene and more noise."""
    image, _ = render(label, rng, brightness=1.0, noise=22.0)
    pixels = np.clip(np.asarray(image, dtype=np.float32) + 70, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()


def run_cycle(
    remote: RemoteModel,
    station: str,
    cycle: str,
    png: bytes,
    truth: str,
    version: str,
    scenario: str,
) -> dict:
    thresholds = load_use_case_config(UseCase.QUALITY).thresholds
    meta = FrameMeta(
        frame_id=f"cycle:{station}:{cycle}", workstation_id=station, camera_id="CAM-Q-SIM"
    )
    stats = image_stats(png)
    try:
        call = remote.predict(base64.b64encode(png).decode(), f"simulator {scenario}")
    except Exception as exc:  # noqa: BLE001 - network/timeout: the part can never be OK
        call = {
            "http_status": None,
            "latency_ms": None,
            "prediction": None,
            "error": repr(exc)[:200],
        }
    record = {
        "station_id": station,
        "cycle_id": cycle,
        "ts": datetime.now(UTC).isoformat(),
        "model_version": version,
        **stats,
        "ground_truth": truth,
        "scenario": scenario,
        "source": "serving",
        "simulated_machine": True,
        "synthetic_image": True,
        "http_status": call["http_status"],
        "latency_ms": call["latency_ms"],
    }
    if call["http_status"] != 200 or not call["prediction"]:
        record.update(
            predicted_label=None,
            anomaly_score=None,
            verdict=PartVerdict.ERROR.value,
            error=call["error"],
        )
        return record
    score = float(call["prediction"]["anomaly_score"])
    event = to_event(
        AnalysisResult(
            use_case=UseCase.QUALITY,
            score=score,
            latency_ms=call["latency_ms"],
            model_name=MODEL,
            model_version=version,
            details=QualityDetails(),
        ),
        meta,
        thresholds,
    )
    edge_event = EdgeEvent(
        event_id=str(uuid.uuid4()),
        event_type="inference",
        station_id=station,
        edge_sequence=1,
        occurred_at=event.frame.timestamp,
        simulated=True,
        camera_id=meta.camera_id,
        cycle_id=cycle,
        use_case=UseCase.QUALITY,
        model_name=MODEL,
        model_version=version,
        score=score,
        decision=event.decision,
        payload=InferencePayload(event=event),
    )
    record.update(
        predicted_label=call["prediction"]["class"],
        anomaly_score=score,
        decision=event.decision.value,
        verdict=verdict_from_decision(event.decision).value,
        argos_event_id=event.event_id,
        edge_event_valid=edge_event.schema_version,
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=4)
    parser.add_argument(
        "--drift", action="store_true", help="use drifted (brighter, noisier) images"
    )
    parser.add_argument("--station", default="SIM-WS-01")
    args = parser.parse_args(argv)
    if args.cycles > remaining_inferences():
        print(f"refused: {args.cycles} cycles, {remaining_inferences()} remote inferences left")
        return 1
    remote = RemoteModel()
    version = remote.served_version()
    scenario = "drift" if args.drift else "reference"
    rng = np.random.default_rng(DRIFT_SEED)
    images = sample_images(args.cycles, split="validation")
    records = []
    print(
        f"SIMULATED machine {args.station} - scenario {scenario} - served model {MODEL} v{version}"
    )
    for index, item in enumerate(images):
        cycle = f"SIM-{datetime.now(UTC):%Y%m%dT%H%M%S}-{index:03d}"
        png = (
            drifted_image(item["label"], rng)
            if args.drift
            else (LOCAL_HOME / "dataset" / "synthetic-v1" / item["file"]).read_bytes()
        )
        record = run_cycle(remote, args.station, cycle, png, item["label"], version, scenario)
        records.append(record)
        print(
            f"  {cycle} truth={record['ground_truth']:<3} HTTP {record['http_status']} "
            f"{record['latency_ms'] or 0:>7.1f} ms score={record['anomaly_score']} "
            f"label={record['predicted_label']} "
            f"-> ARGOS {record.get('decision')} / {record['verdict']}"
        )
    with TELEMETRY.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    path = save_result(f"simulator_{scenario}", {"records": records})
    print(f"{len(records)} telemetry records appended to {TELEMETRY}; saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
