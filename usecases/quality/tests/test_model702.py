"""Tests of the qualite702 analyzer, when its weights are on this machine.

The weights are never versioned (data/models/quality/qualite702_v1/modele.pt): the tests
are SKIPPED in CI and on a machine without them.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from usecases.quality.model702 import REPO_ROOT, Quality702Analyzer
from visionhub.config import load_use_case_config
from visionhub.contracts import FrameMeta, UseCase
from visionhub.decision import decide

WEIGHTS = REPO_ROOT / "data/models/quality/qualite702_v1/modele.pt"
PHOTOS = REPO_ROOT / "data/raw/quality/702"
pytestmark = pytest.mark.skipif(not WEIGHTS.exists(), reason="qualite702 weights not available")


@pytest.fixture(scope="module")
def analyzer():
    config = load_use_case_config(UseCase.QUALITY)
    a = Quality702Analyzer()
    a.load({**config.params, "device": "cpu"})
    return a, config.thresholds


def test_output_respects_the_contract(analyzer):
    a, _ = analyzer
    result = a.analyze(
        np.zeros((86, 126, 3), np.uint8), FrameMeta(frame_id="0", workstation_id="W", camera_id="Q")
    )
    assert 0.0 <= result.score <= 1.0 and result.details.kind == "quality"
    assert set(a.last["probabilities"]) == {"NOK_DOUBLE", "NOK_SANS", "OK"}


@pytest.mark.skipif(not PHOTOS.exists(), reason="quality photos not available")
@pytest.mark.parametrize("folder, expected", [("OK", "conforme"), ("NOK", "anomalie")])
def test_one_photo_of_each_class(analyzer, folder, expected):
    a, thresholds = analyzer
    photo = sorted(Path(PHOTOS, folder).glob("*.jpg"))[0]
    result = a.analyze(
        cv2.imread(str(photo)), FrameMeta(frame_id=photo.name, workstation_id="W", camera_id="Q")
    )
    assert decide(result.score, thresholds).value == expected
