"""Tests of the single-photo chain: alignment, views, learned normal, slots, naming.

Everything runs on the synthetic station generated in memory (make_samples): no data/,
no model. The real dataset is tested in test_presse_5s.py (skipped without the data).
"""

import cv2
import numpy as np

from usecases.workstation import make_samples as samples
from usecases.workstation.align import align_to_reference
from usecases.workstation.detector import Detection
from usecases.workstation.model import ALIGNMENT_FAILED, UNKNOWN, ZoneWorkstationAnalyzer
from usecases.workstation.station import analyzer_params, load_station
from visionhub.contracts import FrameMeta

REFERENCE = samples.station()
ZONES = {
    "keep_clear": samples.KEEP_CLEAR,
    "bench": [(0.42, 0.20), (0.58, 0.20), (0.58, 0.80), (0.42, 0.80)],
}
SLOTS = {"caliper": [(0.24, 0.09), (0.37, 0.09), (0.37, 0.41), (0.24, 0.41)]}
META = FrameMeta(frame_id="0", workstation_id="W", camera_id="C")


class FakeDetector:
    name = "fake"

    def __init__(self, detections):
        self.detections = detections

    def __call__(self, image):
        return self.detections


def analyzer(views=None, detector=None, **params) -> ZoneWorkstationAnalyzer:
    a = ZoneWorkstationAnalyzer()
    a.load(
        {
            "detector": "none",
            "align": True,
            "empty_zones": ZONES,
            "element_slots": SLOTS,
            "views": views,
            **params,
        }
    )
    if views is None:
        a.reset_reference(REFERENCE)
    if detector is not None:
        a.detector = detector
    return a


def with_bottle(image, x, y):
    """A small object that NORMALLY sits on the bench, at a position that varies."""
    out = image.copy()
    cv2.circle(out, samples._px(x, y), 18, (230, 230, 240), -1)
    return out


# ------------------------------------------------------------------ alignment and views


def test_alignment_recovers_a_camera_shift():
    h, w = REFERENCE.shape[:2]
    rotation = cv2.getRotationMatrix2D((w / 2, h / 2), 2.0, 1.02)
    rotation[:, 2] += (15, -10)
    shot = cv2.warpAffine(REFERENCE, rotation, (w, h), borderMode=cv2.BORDER_REFLECT)
    raw_diff = np.abs(shot.astype(int) - REFERENCE).mean()
    alignment = align_to_reference(shot, REFERENCE)
    assert alignment.ok, alignment.reason
    aligned_diff = np.abs(alignment.aligned.astype(int) - REFERENCE)[alignment.valid].mean()
    assert aligned_diff < raw_diff / 3


def test_unrelated_photo_gives_a_verifier_not_a_guess():
    noise = np.random.default_rng(0).integers(0, 256, REFERENCE.shape, dtype=np.uint8)
    result = analyzer().analyze(noise, META)
    assert result.details.misplaced == [ALIGNMENT_FAILED]
    assert 0.4 <= result.score < 0.7


def test_the_view_that_aligns_is_used(tmp_path):
    other = np.random.default_rng(1).integers(0, 256, REFERENCE.shape, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "other.png"), other)
    cv2.imwrite(str(tmp_path / "station.png"), REFERENCE)
    views = [
        {"name": "other", "reference_image": str(tmp_path / "other.png"), "empty_zones": ZONES},
        {"name": "station", "reference_image": str(tmp_path / "station.png"), "empty_zones": ZONES},
    ]
    a = analyzer(views=views)
    result = a.analyze(samples.camera_jitter(REFERENCE, np.random.default_rng(2)), META)
    assert a.last_view == "station"
    assert result.score == 0.0, result.details


# ------------------------------------------------------------------ learned normal


def test_learned_normal_ignores_normal_variation_but_catches_new_objects(tmp_path):
    rng = np.random.default_rng(3)
    goods = []
    for i, x in enumerate(np.linspace(0.45, 0.55, 8)):  # the bottle moves a little
        path = tmp_path / f"good_{i}.png"
        cv2.imwrite(str(path), samples.camera_jitter(with_bottle(REFERENCE, x, 0.5), rng))
        goods.append(str(path))
    photo = samples.camera_jitter(with_bottle(REFERENCE, 0.52, 0.5), rng)  # normal position

    single = analyzer()  # one reference image only: the bottle is "new" for it
    assert f"{UNKNOWN}@bench" in single.analyze(photo, META).details.misplaced

    learned = analyzer()
    learned.learn_normal(goods)  # after the reference is set
    # 8 conforming photos + the reference image itself
    assert learned.views[0].normal is not None and learned.views[0].normal.count == 9
    assert learned.analyze(photo, META).score == 0.0

    cluttered = photo.copy()
    samples.box(cluttered, 0.72, 0.65)  # something in the keep-clear zone
    result = learned.analyze(cluttered, META)
    assert f"{UNKNOWN}@keep_clear" in result.details.misplaced and result.score >= 0.7


# ------------------------------------------------------------------ slots and naming


def test_element_removed_from_its_slot_is_missing():
    image = REFERENCE.copy()
    cv2.rectangle(image, samples._px(0.25, 0.10), samples._px(0.36, 0.40), (90, 90, 95), -1)
    result = analyzer().analyze(samples.camera_jitter(image, np.random.default_rng(4)), META)
    assert result.details.missing == ["caliper"]
    assert result.score >= 0.7


def zone_box():
    return (
        int(0.75 * samples.W),
        int(0.65 * samples.H),
        int(0.85 * samples.W),
        int(0.85 * samples.H),
    )


def test_detector_alone_never_raises_an_alert():
    """An object detected where nothing changed (normally there) is not a problem."""
    result = analyzer(detector=FakeDetector([Detection("bottle", 0.9, zone_box())])).analyze(
        REFERENCE, META
    )
    assert result.score == 0.0 and result.details.misplaced == []


def test_detector_names_a_change():
    image = REFERENCE.copy()
    x1, y1, x2, y2 = zone_box()
    image[y1:y2, x1:x2] = (30, 30, 30)
    result = analyzer(detector=FakeDetector([Detection("cell phone", 0.5, zone_box())])).analyze(
        image, META
    )
    assert result.details.misplaced == ["cell phone@keep_clear"]
    assert result.score >= 0.7  # the stronger of detector confidence and size of change


def test_huge_box_around_a_small_change_does_not_name_it():
    image = REFERENCE.copy()
    samples.cup(image, 0.80, 0.75)
    scene = FakeDetector([Detection("refrigerator", 0.8, (0, 0, samples.W, samples.H))])
    result = analyzer(detector=scene).analyze(image, META)
    assert result.details.misplaced == [f"{UNKNOWN}@keep_clear"]


# ------------------------------------------------------------------ station file


def test_station_file_is_valid_without_the_data(tmp_path):
    station = load_station("presse_5s", tmp_path)  # empty data root
    assert [v["name"] for v in station["views"]] == ["planche", "pilote"]
    for view in station["views"]:
        assert {"red_zone", "workbench"} <= set(view["empty_zones"])
    params = analyzer_params(station)
    assert params["normal_images"] == []  # no dataset here: no normal photos
    a = ZoneWorkstationAnalyzer()
    a.load({"detector": "none", "align": True, **params})  # loads, references missing
    assert a.analyze(REFERENCE, META).score <= 1.0


# ------------------------------------------------------------------ rendering


def test_render_draws_on_the_original_photo_with_a_verdict_banner():
    from usecases.workstation.render import describe, render
    from visionhub.contracts import Decision

    photo = samples.camera_jitter(REFERENCE, np.random.default_rng(5))
    samples.box(photo, 0.72, 0.65)
    a = analyzer()
    result = a.analyze(photo, META)
    shown = render(photo, a, result, Decision.ANOMALIE, scale=1.0)
    assert shown.shape[1] == photo.shape[1] and shown.shape[0] == photo.shape[0] + 48
    assert any("keep_clear" in line for line in describe(result))
