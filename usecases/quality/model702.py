"""Quality analyzer for part 702: OK / NOK classification of the quality camera photo.

The model comes from the ``quality`` branch (kit_integration_qualite702, model
``qualite702 v1``): a YOLO26n classifier (Ultralytics) with 3 classes
NOK_DOUBLE (more than one seal in the groove), NOK_SANS (no seal), OK (one seal).

Same pre- and post-processing as the kit (``qualite702/inference.py``):
- pre-processing done by Ultralytics (short side resized to ``imgsz``, centre crop);
- score = sum of the probabilities of the NOK* classes (higher = worse, as the contract
  wants); the decision layer compares it with the thresholds of config.yaml
  (low = high = the kit's ``seuil_nok``: OK / NOK, no "to check" zone, like the kit).

``last`` keeps the details of the last photo for the operator screen: verdict, defect
type, probabilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from visionhub.analyzer import Analyzer
from visionhub.contracts import AnalysisResult, FrameMeta, QualityDetails, UseCase

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS = {
    "OK": "1 seal in the groove: conforming part",
    "NOK_SANS": "no seal in the groove",
    "NOK_DOUBLE": "more than one seal in the groove",
}


class Quality702Analyzer(Analyzer):
    use_case = UseCase.QUALITY
    name = "qualite702"
    version = "v1"

    def load(self, config: dict[str, Any]) -> None:
        from ultralytics import YOLO, settings  # heavy import here, not at module level

        settings.update({"sync": False})  # team rule: no usage statistics sent anywhere
        weights = Path(config.get("weights", "data/models/quality/qualite702_v1/modele.pt"))
        weights = weights if weights.is_absolute() else REPO_ROOT / weights
        if not weights.exists():
            raise FileNotFoundError(f"Quality weights not found: {weights}")
        self.model = YOLO(str(weights), task="classify")
        self.device = str(config.get("device", "cpu"))
        self.imgsz = int(config.get("imgsz", 128))
        self.classes = list(config.get("classes", ["NOK_DOUBLE", "NOK_SANS", "OK"]))
        names = [self.model.names[k] for k in sorted(self.model.names)]
        if names != self.classes:  # same guard as the kit
            raise ValueError(f"Classes of config.yaml {self.classes} differ from the model {names}")
        self.nok = [i for i, c in enumerate(self.classes) if c.startswith("NOK")]
        self.threshold = float(config.get("seuil_nok", 0.6365))
        self.last: dict[str, Any] = {}
        # Warm-up: the first inference is slow on CPU, pay it at startup.
        self.model.predict(
            np.zeros((self.imgsz, self.imgsz, 3), np.uint8),
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )

    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        result = self.model.predict(image, imgsz=self.imgsz, device=self.device, verbose=False)[0]
        probs = np.asarray(result.probs.data.cpu().numpy(), dtype=float)
        score = float(probs[self.nok].sum())
        defect = (
            self.classes[max(self.nok, key=lambda i: probs[i])] if score >= self.threshold else None
        )
        self.last = {
            "verdict": "NOK" if defect else "OK",
            "defect": defect,
            "label": LABELS.get(defect or "OK", defect),
            "score_nok": round(score, 4),
            "probabilities": {
                c: round(float(p), 4) for c, p in zip(self.classes, probs, strict=True)
            },
        }
        return AnalysisResult(
            use_case=self.use_case,
            score=min(1.0, max(0.0, score)),
            model_name=self.name,
            model_version=self.version,
            details=QualityDetails(),
        )
