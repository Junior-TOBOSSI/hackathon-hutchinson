"""Inference adapter for Databricks Model Serving (from the DBX-00 validated client).

- ``EndpointClient``: image -> base64 -> HTTPS call -> normalized ``EndpointPrediction``
  (class, anomaly score, latency, served version). Every failure RAISES
  ``InferenceError``: a failed call can never be read as a conforming part.
- ``DatabricksQualityAnalyzer``: an ARGOS ``Analyzer`` (``use_case = quality``) returning
  the shared ``AnalysisResult``. It is NOT enabled anywhere: activation is a one-line
  change in ``usecases/quality/config.yaml``, owned by the Quality group (see
  mlops/docs/dbx-01-integration.md).

Expected endpoint contract (the DBX-00 pyfunc): input ``dataframe_records`` with
``image_base64``; output ``predictions`` with ``class`` and ``anomaly_score`` (P(NOK),
higher = worse). Another model only needs the same input/output (see the delivery contract).
"""

from __future__ import annotations

import base64
import time
from typing import Any

import numpy as np
import requests
from pydantic import BaseModel, ConfigDict

from visionhub.analyzer import Analyzer
from visionhub.contracts import AnalysisResult, FrameMeta, QualityDetails, UseCase


class InferenceError(RuntimeError):
    """Remote inference failed (HTTP error, timeout, malformed answer)."""


class EndpointPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    predicted_class: str
    anomaly_score: float
    latency_ms: float
    endpoint: str
    model: str | None
    served_version: str | None


def encode_image(image: np.ndarray | bytes) -> str:
    """BGR uint8 array (OpenCV convention) or encoded bytes -> base64 PNG."""
    if isinstance(image, bytes):
        return base64.b64encode(image).decode()
    import cv2

    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise InferenceError("cannot encode the image as PNG")
    return base64.b64encode(buffer.tobytes()).decode()


class EndpointClient:
    def __init__(
        self, endpoint: str, workspace=None, timeout_s: int = 30, served_cache_s: int = 60
    ) -> None:
        if workspace is None:
            from mlops.databricks.settings import DatabricksSettings

            settings = DatabricksSettings.from_env()
            settings.apply_process_environment()
            from databricks.sdk import WorkspaceClient

            workspace = WorkspaceClient(profile=settings.profile)
        self.w = workspace
        self.endpoint = endpoint
        self.timeout_s = timeout_s
        self.url = f"{self.w.config.host.rstrip('/')}/serving-endpoints/{endpoint}/invocations"
        self._served: tuple[float, str | None, str | None] | None = None
        self._served_cache_s = served_cache_s

    def served(self) -> tuple[str | None, str | None]:
        """(model, version) the endpoint really serves, cached briefly."""
        if self._served and time.time() - self._served[0] < self._served_cache_s:
            return self._served[1], self._served[2]
        endpoint = self.w.serving_endpoints.get(self.endpoint)
        entities = (endpoint.config.served_entities if endpoint.config else None) or []
        model, version = (
            (entities[0].entity_name, entities[0].entity_version) if entities else (None, None)
        )
        self._served = (time.time(), model, version)
        return model, version

    def predict(self, image: np.ndarray | bytes) -> EndpointPrediction:
        payload = {"dataframe_records": [{"image_base64": encode_image(image)}]}
        headers = {"Content-Type": "application/json", **self.w.config.authenticate()}
        start = time.perf_counter()
        try:
            response = requests.post(
                self.url, headers=headers, json=payload, timeout=self.timeout_s
            )
        except requests.RequestException as exc:
            raise InferenceError(f"{self.endpoint}: {type(exc).__name__}") from exc
        latency_ms = (time.perf_counter() - start) * 1000
        if response.status_code != 200:
            raise InferenceError(
                f"{self.endpoint}: HTTP {response.status_code} {response.text[:200]}"
            )
        try:
            prediction = response.json()["predictions"][0]
            score = float(prediction["anomaly_score"])
            label = str(prediction["class"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise InferenceError(
                f"{self.endpoint}: malformed answer {response.text[:200]}"
            ) from exc
        if not 0.0 <= score <= 1.0:
            raise InferenceError(f"{self.endpoint}: anomaly_score out of [0, 1]: {score}")
        model, version = self.served()
        return EndpointPrediction(
            predicted_class=label,
            anomaly_score=score,
            latency_ms=round(latency_ms, 1),
            endpoint=self.endpoint,
            model=model,
            served_version=version,
        )


class DatabricksQualityAnalyzer(Analyzer):
    """Quality analyzer backed by a Databricks serving endpoint (not enabled by default).

    ``config.yaml`` params: ``endpoint`` (required), ``timeout_s`` (default 30).
    """

    use_case = UseCase.QUALITY
    name = "databricks-serving"
    version = "0.1.0"

    def load(self, config: dict[str, Any]) -> None:
        self.client = EndpointClient(config["endpoint"], timeout_s=int(config.get("timeout_s", 30)))

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        prediction = self.client.predict(
            image
        )  # raises InferenceError: the pipeline records an error
        return AnalysisResult(
            use_case=self.use_case,
            score=prediction.anomaly_score,
            model_name=prediction.model or self.name,
            model_version=prediction.served_version or "unknown",
            details=QualityDetails(),
        )
