"""Package the group's fitted Workstation analyzer with its real reference images.

The model reconstructs statistical normality from the verified good photos on load.
No learned result is invented; no neural network is trained by this wrapper.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

try:
    from mlflow.pyfunc import PythonModel
except ImportError:  # local checks without MLflow
    PythonModel = object


class WorkstationModel(PythonModel):
    def __init__(self, section: str):
        self.section = section

    def load_context(self, context):
        from usecases.workstation import evaluate as group_eval
        from usecases.workstation.station import load_station, normal_photos
        from visionhub.config import load_use_case_config
        from visionhub.contracts import UseCase

        root = Path(context.artifacts["data_root"])
        station = load_station(self.section, root)
        config = load_use_case_config(UseCase.WORKSTATION)
        params = {
            **{k: v for k, v in config.params.items() if k not in ("station", "data_root")},
            "detector": "coco",
            "device": "cpu",
            "weights": context.artifacts["weights"],
        }
        group_eval.load_use_case_config = lambda use_case: load_use_case_config(use_case)
        self.analyzer, self.thresholds = group_eval.build_analyzer(
            station, normal_photos(station), params
        )

    def predict(self, context, model_input, params=None):
        import cv2
        import pandas as pd

        from visionhub.contracts import FrameMeta
        from visionhub.decision import decide

        rows = []
        for index, path in enumerate(model_input["path"]):
            image = cv2.imread(str(path))
            if image is None:
                raise FileNotFoundError(path)
            start = time.perf_counter()
            result = self.analyzer.analyze(
                image, FrameMeta(frame_id=str(index), workstation_id="MODEL", camera_id="MODEL")
            )
            latency = (time.perf_counter() - start) * 1000
            decision = decide(result.score, self.thresholds).value
            rows.append(
                {
                    "decision": decision,
                    "score": float(result.score),
                    "latency_ms": latency,
                    "result_json": json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                }
            )
        return pd.DataFrame(rows, columns=["decision", "score", "latency_ms", "result_json"])


def log_workstation_model(mlflow, section, data_root, weights, kit, repo_root, work):
    """Bundle only required source packages and data artifacts into an MLflow candidate."""
    source = work / "model_code"
    shutil.copytree(
        kit / "usecases",
        source / "usecases",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )
    shutil.copytree(
        repo_root / "visionhub",
        source / "visionhub",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, Schema

    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "path")]),
        outputs=Schema(
            [
                ColSpec("string", "decision"),
                ColSpec("double", "score"),
                ColSpec("double", "latency_ms"),
                ColSpec("string", "result_json"),
            ]
        ),
    )
    return mlflow.pyfunc.log_model(
        name="model",
        python_model=WorkstationModel(section),
        artifacts={"data_root": str(data_root), "weights": str(weights)},
        code_paths=[str(source / "usecases"), str(source / "visionhub")],
        signature=signature,
        pip_requirements=[
            "numpy==1.26.4",
            "opencv-python==4.11.0.86",
            "ultralytics==8.4.219",
            "torch==2.5.1",
            "torchvision==0.20.1",
            "pydantic>=2.0",
            "pydantic-settings>=2.0",
            "pyyaml",
        ],
    )
