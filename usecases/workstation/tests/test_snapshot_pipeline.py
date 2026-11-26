"""Tests of the single-photo chain: clean capture, alignment, element slots, variants,
evaluation. Everything runs on synthetic images generated in memory (no data/, no model)."""

import cv2
import numpy as np
import pytest

from usecases.workstation import make_samples as samples
from usecases.workstation.align import align_to_reference
from usecases.workstation.clean_capture import clean_capture, find_video_area
from usecases.workstation.evaluate import evaluate, summary
from usecases.workstation.make_variants import camera_jitter, generate, write
from usecases.workstation.model import ALIGNMENT_FAILED, ZoneWorkstationAnalyzer
from visionhub.contracts import FrameMeta, Thresholds

REFERENCE = samples.station()
STATION = {
    "name": "synthetic",
    "empty_zones": {"keep_clear": samples.KEEP_CLEAR},
    "element_slots": {
        "caliper": [(0.24, 0.09), (0.37, 0.09), (0.37, 0.41), (0.24, 0.41)],
        "parts_tray": [(0.04, 0.59), (0.36, 0.59), (0.36, 0.93), (0.04, 0.93)],
    },
}
META = FrameMeta(frame_id="0", workstation_id="W", camera_id="C")


def snapshot_analyzer(**params) -> ZoneWorkstationAnalyzer:
    analyzer = ZoneWorkstationAnalyzer()
    analyzer.load(
        {
            "detector": "none",
            "align": True,
            "empty_zones": STATION["empty_zones"],
            "element_slots": STATION["element_slots"],
            **params,
        }
    )
    analyzer.reset_reference(REFERENCE)
    return analyzer


# ------------------------------------------------------------------ alignment


def test_alignment_recovers_a_camera_shift():
    """Pure geometric shift (no light change): alignment must bring the photo back."""
    h, w = REFERENCE.shape[:2]
    rotation = cv2.getRotationMatrix2D((w / 2, h / 2), 2.0, 1.02)  # 2 degrees, 2 % zoom
    rotation[:, 2] += (15, -10)  # and a shift of a few pixels
    shot = cv2.warpAffine(REFERENCE, rotation, (w, h), borderMode=cv2.BORDER_REFLECT)
    raw_diff = np.abs(shot.astype(int) - REFERENCE).mean()
    alignment = align_to_reference(shot, REFERENCE)
    assert alignment.ok, alignment.reason
    aligned_diff = np.abs(alignment.aligned.astype(int) - REFERENCE)[alignment.valid].mean()
    assert aligned_diff < raw_diff / 3


def test_alignment_fails_on_an_unrelated_image():
    noise = np.random.default_rng(0).integers(0, 256, REFERENCE.shape, dtype=np.uint8)
    assert not align_to_reference(noise, REFERENCE).ok


def test_failed_alignment_gives_a_verifier_not_a_guess():
    noise = np.random.default_rng(0).integers(0, 256, REFERENCE.shape, dtype=np.uint8)
    result = snapshot_analyzer().analyze(noise, META)
    assert result.details.misplaced == [ALIGNMENT_FAILED]
    assert 0.4 <= result.score < 0.7


# ------------------------------------------------------------------ element slots


def test_shifted_but_tidy_station_is_conforme():
    shot = camera_jitter(REFERENCE, np.random.default_rng(2))
    result = snapshot_analyzer().analyze(shot, META)
    assert result.score == 0.0, result.details


def test_element_removed_from_its_slot_is_missing():
    image = REFERENCE.copy()
    cv2.rectangle(image, samples._px(0.25, 0.10), samples._px(0.36, 0.40), (90, 90, 95), -1)
    result = snapshot_analyzer().analyze(camera_jitter(image, np.random.default_rng(3)), META)
    assert result.details.missing == ["caliper"]
    assert result.score >= 0.7


# ------------------------------------------------------------------ clean capture


def test_clean_capture_crops_the_frame_and_erases_overlays():
    # Known limit: overlays are found by colour, so the scene must not contain the same
    # bright green / magenta (true for the client capture). Grey scene here.
    video = cv2.cvtColor(cv2.cvtColor(REFERENCE, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    screenshot = np.full((900, 1400, 3), 240, np.uint8)  # player UI around
    screenshot[80:900, 100:1300] = (24, 124, 28)  # green frame / banners (BGR)
    screenshot[150:870, 110:1290] = cv2.resize(video, (1180, 720))
    cv2.rectangle(screenshot, (600, 300), (900, 600), (255, 0, 255), 3)  # magenta overlay

    x1, y1, x2, y2 = find_video_area(screenshot)
    assert abs(x1 - 110) <= 4 and abs(y1 - 150) <= 4 and abs(x2 - 1290) <= 4 and abs(y2 - 870) <= 4
    clean, mask = clean_capture(screenshot)
    hsv = cv2.cvtColor(clean, cv2.COLOR_BGR2HSV)
    assert cv2.inRange(hsv, (140, 150, 150), (165, 255, 255)).sum() == 0  # no magenta left
    assert (mask > 0).mean() < 0.05  # only the overlay was erased


# ------------------------------------------------------------------ variants + evaluation


def test_variants_and_evaluation_end_to_end(tmp_path):
    variants = generate(REFERENCE, STATION, np.random.default_rng(0), n=4)
    kinds = {v.kind for v in variants}
    assert {"ok", "object_outside", "missing_caliper", "object_in_keep_clear"} <= kinds
    write(variants, tmp_path)

    rows = evaluate(snapshot_analyzer(), Thresholds(low=0.4, high=0.7), tmp_path)
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    assert sum(r["right_reason"] for r in alerts) / len(alerts) >= 0.9
    assert sum(r["decision"] != "conforme" for r in normal) == 0
    assert "DETECTION" in summary(rows)


@pytest.mark.parametrize("seed", [0, 1])
def test_jitter_keeps_size_and_type(seed):
    shot = camera_jitter(REFERENCE, np.random.default_rng(seed))
    assert shot.shape == REFERENCE.shape and shot.dtype == np.uint8
