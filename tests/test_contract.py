"""CONTRACT TEST: every analyzer declared in usecases/*/config.yaml must pass it.

This is what guarantees that a team's real model plugs into the platform. It loads the
analyzer exactly as the platform does (through the registry and its config.yaml), then
checks the shape of its outputs. Run it with:

    pytest tests/test_contract.py
"""

import os
import time

import numpy as np
import pytest

from visionhub.analyzer import Analyzer
from visionhub.config import Settings, load_use_case_config
from visionhub.contracts import (
    AnalysisResult,
    FrameMeta,
    QualityDetails,
    SafetyDetails,
    UseCase,
    WorkstationDetails,
)
from visionhub.registry import Registry, import_class

EXPECTED_DETAILS = {
    UseCase.QUALITY: QualityDetails,
    UseCase.WORKSTATION: WorkstationDetails,
    UseCase.SAFETY: SafetyDetails,
}
# Upper bound for one analyze() call on CPU. Raise it with CONTRACT_MAX_SECONDS if needed.
MAX_SECONDS = float(os.environ.get("CONTRACT_MAX_SECONDS", "2.0"))


def sample_images() -> list[np.ndarray]:
    rng = np.random.default_rng(0)
    return [
        np.zeros((480, 640, 3), dtype=np.uint8),
        rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8),
        rng.integers(0, 256, (240, 320, 3), dtype=np.uint8),
        np.full((300, 300, 3), 255, dtype=np.uint8),
    ]


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry(Settings(_env_file=None, enabled_use_cases=list(UseCase))).load()


@pytest.mark.parametrize("use_case", list(UseCase), ids=lambda u: u.value)
def test_analyzer_class_is_declared_correctly(use_case):
    config = load_use_case_config(use_case)
    cls = import_class(config.analyzer_class)
    assert issubclass(cls, Analyzer)
    assert cls.use_case == use_case
    assert isinstance(cls.name, str) and cls.name
    assert isinstance(cls.version, str) and cls.version
    assert config.thresholds.low <= config.thresholds.high


@pytest.mark.parametrize("use_case", list(UseCase), ids=lambda u: u.value)
def test_analyzer_loads_through_registry(registry, use_case):
    info = {i.use_case: i for i in registry.info()}[use_case]
    assert info.status == "ok", f"Analyzer failed to load: {info.error}"


@pytest.mark.parametrize("use_case", list(UseCase), ids=lambda u: u.value)
def test_analyzer_output_respects_contract(registry, use_case):
    analyzer = registry.get(use_case)
    assert analyzer is not None
    for i, image in enumerate(sample_images()):
        meta = FrameMeta(frame_id=f"contract-{i}", workstation_id="WS-T", camera_id="CAM-T")
        start = time.perf_counter()
        result = analyzer.analyze(image.copy(), meta)
        elapsed = time.perf_counter() - start

        assert isinstance(result, AnalysisResult)
        assert result.use_case == use_case
        assert isinstance(result.details, EXPECTED_DETAILS[use_case])
        assert 0.0 <= result.score <= 1.0
        assert result.model_name and result.model_version
        assert elapsed < MAX_SECONDS, f"analyze() took {elapsed:.2f}s (max {MAX_SECONDS}s)"
        # Must survive a JSON round-trip (what the API and the store do).
        assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
