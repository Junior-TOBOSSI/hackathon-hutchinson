"""Tests of the zone analyzer. Images are generated in memory (make_samples), no model needed."""

import numpy as np
import pytest

from usecases.workstation import make_samples as samples
from usecases.workstation.detector import Detection
from usecases.workstation.model import UNKNOWN, ZoneWorkstationAnalyzer
from usecases.workstation.zones import (
    box_overlap,
    changed_blobs,
    polygon_mask,
    validate_polygon,
)
from visionhub.contracts import AnalysisResult, FrameMeta

ZONE = samples.KEEP_CLEAR
REFERENCE = samples.station()
PERSISTENCE = 3


def make(detector=None, **params) -> ZoneWorkstationAnalyzer:
    analyzer = ZoneWorkstationAnalyzer()
    analyzer.load(
        {
            "detector": "none",
            "empty_zones": {"keep_clear": ZONE},
            "persistence_frames": PERSISTENCE,
            "device": "cpu",
            **params,
        }
    )
    analyzer.reset_reference(REFERENCE)
    if detector is not None:
        analyzer.detector = detector
    return analyzer


def run(analyzer, image, times=PERSISTENCE) -> AnalysisResult:
    for i in range(times):
        result = analyzer.analyze(
            image, FrameMeta(frame_id=str(i), workstation_id="W", camera_id="C")
        )
    return result


class FakeDetector:
    name = "fake"

    def __init__(self, detections):
        self.detections = detections

    def __call__(self, image):
        return self.detections


# ------------------------------------------------------------------ geometry


def test_polygon_mask_and_overlap():
    mask = polygon_mask([(0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)], (100, 200))
    assert mask[:, 110:].all() and not mask[:, :90].any()
    assert box_overlap((150, 10, 190, 50), mask) == 1.0
    assert box_overlap((10, 10, 50, 50), mask) == 0.0
    assert 0.4 < box_overlap((80, 10, 120, 50), mask) < 0.6  # across the border


@pytest.mark.parametrize("bad", [[(0, 0), (1, 1)], [(0, 0), (1, 0), (2, 1)], "nope"])
def test_invalid_polygons_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_polygon("z", bad)


def test_colour_change_with_same_brightness_is_seen():
    """Regression: an orange box on the grey bench is invisible in grayscale."""
    image = REFERENCE.copy()
    samples.box(image, 0.72, 0.65)
    mask = polygon_mask(ZONE, image.shape[:2])
    assert changed_blobs(image, REFERENCE, mask, diff_threshold=35, min_area=100)


def test_global_lighting_change_is_not_a_change():
    brighter = np.clip(REFERENCE.astype(np.int16) + 35, 0, 255).astype(np.uint8)
    mask = polygon_mask(ZONE, REFERENCE.shape[:2])
    assert changed_blobs(brighter, REFERENCE, mask, diff_threshold=35, min_area=100) == []


# ------------------------------------------------------------------ scenarios (no model)


@pytest.mark.parametrize("name", [n for n in samples.scenarios() if "conforme" in n])
def test_conforming_scenarios_score_zero(name):
    result = run(make(), samples.scenarios()[name])
    assert result.score == 0.0
    assert result.details.misplaced == []


@pytest.mark.parametrize("name", [n for n in samples.scenarios() if "anomalie" in n])
def test_object_in_zone_is_an_anomaly(name):
    result = run(make(), samples.scenarios()[name])
    assert result.score >= 0.7
    assert result.details.misplaced == [f"{UNKNOWN}@keep_clear"]
    assert any(o.label == UNKNOWN for o in result.details.detected)


def test_short_passage_is_ignored_thanks_to_persistence():
    frames = samples.sequence()
    analyzer = make()
    scores = [
        analyzer.analyze(f, FrameMeta(frame_id=str(i), workstation_id="W", camera_id="C")).score
        for i, f in enumerate(frames)
    ]
    assert max(scores[:16]) == 0.0  # hand passing at frames 8-9: no alert
    assert scores[16 + PERSISTENCE - 2] == 0.0  # cup just put down: not yet confirmed
    assert min(scores[16 + PERSISTENCE - 1 : 30]) >= 0.7  # cup stays: alert
    assert max(scores[30:]) == 0.0  # cup removed: back to conforme


def test_first_frame_becomes_reference_when_none_is_given():
    analyzer = ZoneWorkstationAnalyzer()
    analyzer.load({"detector": "none", "empty_zones": {"z": ZONE}, "reference_image": None})
    assert analyzer.reference is None
    result = run(analyzer, REFERENCE, times=1)
    assert result.score == 0.0 and analyzer.reference is not None


# ------------------------------------------------------------------ with a detector


def zone_box():
    """A box well inside the keep-clear zone, in pixels."""
    return (
        int(0.75 * samples.W),
        int(0.65 * samples.H),
        int(0.85 * samples.W),
        int(0.85 * samples.H),
    )


def test_known_object_in_zone_is_named_and_not_duplicated():
    image = REFERENCE.copy()
    x1, y1, x2, y2 = zone_box()
    image[y1:y2, x1:x2] = (30, 30, 30)  # what the detector "sees"
    analyzer = make(FakeDetector([Detection("cell phone", 0.9, zone_box())]))
    result = run(analyzer, image)
    assert result.details.misplaced == ["cell phone@keep_clear"]
    assert result.score >= 0.9  # the stronger of detector confidence and size of change
    assert [o.label for o in result.details.detected] == ["cell phone"]


def test_hesitant_detector_never_lowers_a_clear_change():
    """Regression: a person found with confidence 0.38 used to HIDE the change (score 0.38,
    conforme) although the reference comparison alone raised an alert."""
    image = REFERENCE.copy()
    x1, y1, x2, y2 = zone_box()
    image[y1:y2, x1:x2] = (30, 30, 30)
    analyzer = make(FakeDetector([Detection("person", 0.38, zone_box())]))
    result = run(analyzer, image)
    assert result.details.misplaced == ["person@keep_clear"]  # named by the detector
    assert result.score >= 0.7  # but scored by the clear change


def test_detection_outside_the_zone_does_not_hide_a_change_inside():
    image = REFERENCE.copy()
    samples.cup(image, 0.80, 0.75)  # in the zone
    # A huge box (the whole bench) contains the cup centre, but only ~13 % of the box lies
    # in the zone (< min_overlap): it is NOT an object in the zone, so it must not
    # "explain away" the cup.
    big_box = (0, 0, samples.W, samples.H)
    analyzer = make(FakeDetector([Detection("dining table", 0.9, big_box)]))
    result = run(analyzer, image)
    assert f"{UNKNOWN}@keep_clear" in result.details.misplaced


ARM_BOX = (int(0.70 * samples.W), int(0.55 * samples.H), samples.W, samples.H)


def test_person_in_zone_is_a_violation_by_default():
    """Client rule: a zone of interest contains neither object NOR person."""
    image = REFERENCE.copy()
    samples.arm(image, 0.80, 0.70)
    result = run(make(FakeDetector([Detection("person", 0.8, ARM_BOX)])), image)
    assert "person@keep_clear" in result.details.misplaced
    assert result.score >= 0.7


def test_ignored_labels_are_not_judged():
    image = REFERENCE.copy()
    samples.arm(image, 0.80, 0.70)
    detector = FakeDetector([Detection("person", 0.8, ARM_BOX)])
    result = run(make(detector, ignore_labels=["person"]), image)
    assert result.score == 0.0
    assert result.details.misplaced == []
    assert [o.label for o in result.details.detected] == ["person"]  # still identified


def test_missing_expected_element():
    analyzer = make(
        FakeDetector([Detection("scissors", 0.8, (10, 10, 50, 50))]),
        expected_objects=["scissors", "cup"],
    )
    result = run(analyzer, REFERENCE)
    assert result.details.missing == ["cup"]
    assert result.score == pytest.approx(0.5)


def test_output_survives_json_round_trip():
    result = run(make(), samples.scenarios()["04_anomalie_cup_in_zone"])
    assert AnalysisResult.model_validate_json(result.model_dump_json()) == result
