"""Object detectors used by the workstation analyzer, behind one small interface.

A detector takes a BGR image and returns a list of ``Detection`` (label, confidence, box in
pixels). Three kinds, chosen with ``detector:`` in config.yaml:

- ``none``  : no model at all. Only the reference-image difference runs (fallback plan).
- ``coco``  : a YOLO model pre-trained on COCO (phone, cup, bottle, scissors, person...).
- ``yoloe`` : YOLOE open-vocabulary model, prompted with element names (``prompts:``).
- a model trained on our own elements is simply ``coco`` with other ``weights``.

Ultralytics is imported INSIDE the class, never at module level, so that this file can be
imported where the library is not installed (CI, contract test).
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = {"coco": "yolo26n.pt", "yoloe": "yoloe-26s-seg.pt"}


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in pixels


class Detector(Protocol):
    name: str

    def __call__(self, image: np.ndarray) -> list[Detection]: ...


class NoDetector:
    """Placeholder when no model is wanted: detects nothing."""

    name = "none"

    def __call__(self, image: np.ndarray) -> list[Detection]:
        return []


class UltralyticsDetector:
    """YOLO26 (COCO or our own weights) or YOLOE (text prompts), through Ultralytics."""

    def __init__(
        self,
        weights: str,
        device: str = "cpu",
        conf: float = 0.35,
        imgsz: int = 640,
        prompts: list[str] | None = None,
    ) -> None:
        from ultralytics import YOLO, settings

        # Team rule: nothing leaves the machine. This turns off Ultralytics usage analytics.
        settings.update({"sync": False})

        path = resolve_weights(weights)
        self.model = YOLO(str(path))
        self.device, self.conf, self.imgsz = device, conf, imgsz
        self.name = Path(weights).stem
        if prompts:
            # YOLOE needs a text encoder (e.g. mobileclip2_b.ts) that Ultralytics looks for,
            # and downloads, in the CURRENT folder: we move next to the weights so that it
            # lands in data/models/ and never at the root of the repository.
            folder = Path(path).parent if isinstance(path, Path) else Path.cwd()
            with contextlib.chdir(folder):
                self._set_prompts(list(prompts))
            self.name += "[" + ",".join(prompts) + "]"
        # Warm-up: the FIRST inference is slow (PyTorch initialisation, ~2-3 s on CPU).
        # Pay that cost at startup, not on the first real image.
        self(np.zeros((imgsz, imgsz, 3), dtype=np.uint8))

    def _set_prompts(self, names: list[str]) -> None:
        """Tell YOLOE which elements to look for. The signature changed across versions."""
        try:
            self.model.set_classes(names, self.model.get_text_pe(names))
        except (TypeError, AttributeError):
            self.model.set_classes(names)

    def __call__(self, image: np.ndarray) -> list[Detection]:
        result = self.model.predict(
            image, device=self.device, conf=self.conf, imgsz=self.imgsz, verbose=False
        )[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []
        boxes = result.boxes.xyxy.cpu().numpy().round().astype(int)
        classes = result.boxes.cls.cpu().numpy().astype(int)
        confidences = result.boxes.conf.cpu().numpy()
        return [
            Detection(result.names[c], float(p), (int(b[0]), int(b[1]), int(b[2]), int(b[3])))
            for b, c, p in zip(boxes, classes, confidences, strict=True)
        ]


def resolve_weights(weights: str) -> Path | str:
    """Relative paths are relative to the repository root (where data/ lives).

    A bare file name ("yolo26n.pt") that does not exist locally is passed as is: Ultralytics
    then downloads the official weights once. Download them into data/models/ for the demo.
    """
    path = Path(weights)
    if path.is_absolute():
        return path
    in_repo = REPO_ROOT / path
    if in_repo.exists() or path.parent != Path("."):
        return in_repo
    return weights


def build_detector(config: dict[str, Any]) -> Detector:
    kind = str(config.get("detector", "none")).lower()
    if kind == "none":
        return NoDetector()
    if kind not in DEFAULT_WEIGHTS:
        raise ValueError(f"detector must be one of none, coco, yoloe; got {kind!r}")
    prompts = list(config.get("prompts") or [])
    if kind == "yoloe" and not prompts:
        raise ValueError("detector 'yoloe' needs a non-empty 'prompts' list")
    return UltralyticsDetector(
        weights=str(config.get("weights") or DEFAULT_WEIGHTS[kind]),
        device=str(config.get("device", "cpu")),
        conf=float(config.get("conf", 0.35)),
        imgsz=int(config.get("imgsz", 640)),
        prompts=prompts if kind == "yoloe" else None,
    )
