import json
from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest
from pydantic import ValidationError

from visionhub.config import Settings
from visionhub.contracts import AnalysisResult, FrameMeta, SafetyDetails, Thresholds, UseCase
from visionhub.integration import export
from visionhub.integration.edge_events import (
    EdgeEvent,
    EdgeEventBatch,
    EquipmentStatusPayload,
    ShiftPayload,
)
from visionhub.integration.fixtures import SHIFT, build_fixtures, edge_batch
from visionhub.integration.mlops import ModelDeployment, ModelRef, RetrainingPolicy
from visionhub.integration.safety_composite import (
    CompositeSafetyAnalyzer,
    MockBehaviorDetector,
    MockPPEDetector,
)
from visionhub.registry import Registry

# ------------------------------------------------------------------ exported artifacts


def test_exported_artifacts_are_up_to_date():
    """Fails when a contract changed without `python -m visionhub.integration.export`."""
    assert export.main(["--check"]) == 0


def test_fixtures_never_contain_images_or_identities():
    text = json.dumps({k: str(v) for k, (_, v) in build_fixtures().items()}).lower()
    for forbidden in ("base64", "data:image", "face", "badge", "employee"):
        assert forbidden not in text


def test_edge_openapi_exposes_historical_and_production_endpoints():
    paths = export.edge_openapi()["paths"]
    for path in ("/health", "/events", "/stats", "/analyze", "/production/parts/{part_id}"):
        assert path in paths


# ------------------------------------------------------------------ edge events


def event(**overrides) -> dict:
    data = dict(
        event_id="0f0f0f0f-aaaa",
        event_type="equipment.status",
        station_id="WS-01",
        edge_sequence=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload=EquipmentStatusPayload(equipment_id="cam", equipment_type="camera", status="ok"),
    )
    data.update(overrides)
    return data


def test_edge_event_rules():
    EdgeEvent(**event())
    with pytest.raises(ValidationError):  # payload kind must match the type
        EdgeEvent(**event(event_type="part.recorded"))
    with pytest.raises(ValidationError):  # naive datetime
        EdgeEvent(**event(occurred_at=datetime(2026, 1, 1)))
    with pytest.raises(ValidationError):  # non-UTC offset
        EdgeEvent(**event(occurred_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))))
    with pytest.raises(ValidationError):
        EdgeEvent(**event(image="base64..."))
    shift = EdgeEvent(**event(event_type="shift.closed", payload=ShiftPayload(shift=SHIFT)))
    assert shift.schema_version == "argos.edge-event/1"


def test_batch_must_be_one_station_in_order():
    batch = edge_batch()
    data = batch.model_dump()
    data["events"] = list(reversed(data["events"]))
    with pytest.raises(ValidationError):
        EdgeEventBatch.model_validate(data)
    data = batch.model_dump()
    data["events"][0]["station_id"] = "WS-02"
    with pytest.raises(ValidationError):
        EdgeEventBatch.model_validate(data)
    round_trip = EdgeEventBatch.model_validate_json(batch.model_dump_json())
    assert round_trip == batch


# ------------------------------------------------------------------ mlops


def test_mlops_rules():
    ref = ModelRef(registered_model="main.argos.quality", version="3")
    assert ref.uri == "models:/main.argos.quality/3"
    with pytest.raises(ValidationError):
        ModelRef(registered_model="argos-quality", version="v3")
    with pytest.raises(ValidationError):  # auto-deploy without approval is impossible
        RetrainingPolicy(use_case="quality", deployment_requires_approval=False)
    with pytest.raises(ValidationError):  # active deployment without approval
        ModelDeployment(
            deployment_id="d",
            station_id="WS-01",
            use_case="quality",
            model=ref,
            package_sha256="0" * 64,
            status="active",
            requested_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


# ------------------------------------------------------------------ safety composition


def composite(ppe=True, behavior=True, **behavior_params) -> CompositeSafetyAnalyzer:
    analyzer = CompositeSafetyAnalyzer()
    path = "visionhub.integration.safety_composite"
    analyzer.load(
        {
            "ppe": {"detector_class": f"{path}:MockPPEDetector"} if ppe else None,
            "behavior": {
                "detector_class": f"{path}:MockBehaviorDetector",
                "params": behavior_params,
            }
            if behavior
            else None,
        }
    )
    return analyzer


def test_composite_respects_the_safety_contract():
    analyzer = composite()
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    for i in range(50):
        meta = FrameMeta(frame_id=f"f{i}", workstation_id="WS-01", camera_id="CAM-01")
        result = analyzer.analyze(image, meta)
        assert isinstance(result.details, SafetyDetails)
        assert 0 <= result.score <= 1
        assert result.model_name == "mock-ppe+mock-behavior"
        assert AnalysisResult.model_validate_json(result.model_dump_json()) == result


def test_composite_score_is_the_worst_and_phone_is_merged():
    analyzer = composite(finding_rate=1.0)
    meta = FrameMeta(frame_id="x", workstation_id="WS-01", camera_id="CAM-01")
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    ppe = MockPPEDetector()
    ppe.load({})
    behavior = MockBehaviorDetector()
    behavior.load({"finding_rate": 1.0})
    expected = max(ppe.detect(image, meta).score, behavior.detect(image, meta).score)
    assert analyzer.analyze(image, meta).score == expected

    found_phone = False
    for i in range(200):
        meta = FrameMeta(frame_id=f"p{i}", workstation_id="WS-01", camera_id="CAM-01")
        findings = behavior.detect(image, meta).findings
        persons = analyzer.analyze(image, meta).details.persons
        if any(f.kind == "phone_use" for f in findings) and persons:
            assert persons[0].phone
            found_phone = True
    assert found_phone


def test_composite_with_missing_detectors_and_bad_class():
    meta = FrameMeta(frame_id="x", workstation_id="WS-01", camera_id="CAM-01")
    empty = composite(ppe=False, behavior=False).analyze(np.zeros((4, 4, 3), np.uint8), meta)
    assert empty.score == 0 and empty.details.person_count == 0
    with pytest.raises(TypeError):
        CompositeSafetyAnalyzer().load({"ppe": {"detector_class": "visionhub.config:Settings"}})


def test_composite_plugs_into_the_registry_unchanged(tmp_path):
    """Same loading path as the platform: config.yaml -> Registry -> Analyzer."""
    (tmp_path / "safety").mkdir()
    (tmp_path / "safety" / "config.yaml").write_text(
        "analyzer_class: visionhub.integration.safety_composite:CompositeSafetyAnalyzer\n"
        "thresholds: {low: 0.4, high: 0.7}\n"
        "params:\n"
        "  ppe: {detector_class: 'visionhub.integration.safety_composite:MockPPEDetector'}\n"
        "  behavior: {detector_class: "
        "'visionhub.integration.safety_composite:MockBehaviorDetector'}\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=None, enabled_use_cases=[UseCase.SAFETY])
    registry = Registry(settings, base_dir=tmp_path).load()
    info = registry.info()[0]
    assert info.status == "ok", info.error
    assert info.thresholds == Thresholds(low=0.4, high=0.7)
