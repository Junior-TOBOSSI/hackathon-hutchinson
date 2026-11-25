"""The interface every use case implements.

A real model (YOLO, PatchCore, ...) only has to subclass ``Analyzer``, fill in the three
class attributes and implement ``load`` and ``analyze``. Nothing else in the code needs
to change: the registry finds the class through ``usecases/<use_case>/config.yaml``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np

from visionhub.contracts import AnalysisResult, FrameMeta, UseCase


class Analyzer(ABC):
    use_case: ClassVar[UseCase]
    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None:
        """Load the model. Called once at startup.

        ``config`` contains the ``params`` section of the use case ``config.yaml``,
        plus ``device`` ("cpu" or "cuda") taken from the global settings.
        """

    @abstractmethod
    def analyze(self, image: np.ndarray, meta: FrameMeta) -> AnalysisResult:
        """Analyze one image.

        ``image`` is a BGR uint8 array of shape (H, W, 3) (OpenCV convention), already
        preprocessed (ROI crop, anonymization). Return an ``AnalysisResult`` whose
        ``score`` is in [0, 1], higher meaning worse. Leave ``latency_ms`` at 0: the
        pipeline measures it.
        """
