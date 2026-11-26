"""MLflow pyfunc model of the DBX-00 POC ("models from code").

Input  (DataFrame): column ``image_base64`` = base64 of a PNG/JPEG image.
Output (DataFrame): ``class`` ("OK" / "NOK") and ``anomaly_score`` = P(NOK) in [0, 1]
                    (higher = worse, the ARGOS score convention).

``features_from_bytes`` is THE preprocessing: the training job and the served model use
the same function, so a served prediction equals a local one for the same image.
"""

from __future__ import annotations

import base64
import io
import json

import mlflow
import numpy as np
import pandas as pd
from PIL import Image

FEATURE_NAMES = (
    [f"orientation_{i}" for i in range(12)]
    + [f"row_profile_{i}" for i in range(8)]
    + [f"col_profile_{i}" for i in range(8)]
    + ["edge_ratio"]
)


def features_from_bytes(raw: bytes) -> np.ndarray:
    """29 position-invariant shape features (grayscale, background level removed).

    - 12-bin histogram of gradient orientations on the strongest edges (a skewed side
      changes the orientation distribution);
    - 8 + 8 bins of edge-pixel profiles along rows / columns of the shape bounding box
      (a gap in a side leaves a hole in one profile);
    - share of edge pixels.
    """
    image = np.asarray(Image.open(io.BytesIO(raw)).convert("L"), dtype=np.float32) / 255.0
    image = image - np.median(image)
    gy, gx = np.gradient(image)
    magnitude = np.hypot(gx, gy)
    strong = magnitude > np.quantile(magnitude, 0.90)
    angle = np.degrees(np.arctan2(gy, gx)) % 180
    hist = np.histogram(angle[strong], bins=12, range=(0, 180), weights=magnitude[strong])[0]
    hist = hist / (hist.sum() + 1e-6)
    ys, xs = np.nonzero(strong)
    rows = np.histogram(ys, bins=8, range=(ys.min(), ys.max() + 1))[0] / len(ys)
    cols = np.histogram(xs, bins=8, range=(xs.min(), xs.max() + 1))[0] / len(xs)
    return np.concatenate([hist, rows, cols, [strong.mean()]]).astype(np.float64)


class ArgosQualityModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        import joblib

        self.classifier = joblib.load(context.artifacts["classifier"])
        with open(context.artifacts["metadata"], encoding="utf-8") as handle:
            self.metadata = json.load(handle)
        self.nok_index = list(self.classifier.classes_).index(self.metadata["nok_label"])
        self.threshold = float(self.metadata["decision_threshold"])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        features = np.stack(
            [features_from_bytes(base64.b64decode(value)) for value in model_input["image_base64"]]
        )
        scores = self.classifier.predict_proba(features)[:, self.nok_index]
        return pd.DataFrame(
            {
                "class": np.where(scores >= self.threshold, "NOK", "OK"),
                "anomaly_score": scores.astype(float),
            }
        )


mlflow.models.set_model(ArgosQualityModel())
