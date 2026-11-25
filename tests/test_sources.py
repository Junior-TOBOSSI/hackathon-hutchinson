import itertools

import cv2
import numpy as np
import pytest

from visionhub.config import Settings
from visionhub.preprocess import crop_roi, preprocess
from visionhub.sources import folder_source, open_source, synthetic_frame


def test_synthetic_source_is_default_and_yields_bgr_images():
    settings = Settings(_env_file=None)
    assert settings.source == "synthetic"
    frames = list(itertools.islice(open_source(settings), 3))
    for frame in frames:
        assert frame.dtype == np.uint8 and frame.ndim == 3 and frame.shape[2] == 3


def test_synthetic_frame_is_deterministic():
    assert np.array_equal(synthetic_frame(5, seed=1), synthetic_frame(5, seed=1))


def test_folder_source_loops(tmp_path):
    for i in range(2):
        cv2.imwrite(str(tmp_path / f"{i}.png"), synthetic_frame(i))
    (tmp_path / "notes.txt").write_text("ignored")
    frames = list(itertools.islice(folder_source(str(tmp_path)), 5))
    assert len(frames) == 5


def test_folder_source_empty_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        next(folder_source(str(tmp_path)))


def test_crop_roi():
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    assert crop_roi(image, None).shape == (100, 200, 3)
    assert crop_roi(image, (10, 20, 50, 30)).shape == (30, 50, 3)
    assert crop_roi(image, (180, 90, 50, 50)).shape == (10, 20, 3)  # clamped
    assert crop_roi(image, (500, 500, 10, 10)).shape == (100, 200, 3)  # outside -> ignored


def test_preprocess_uses_settings():
    settings = Settings(_env_file=None, roi="0,0,64,32", anonymize=True)
    out = preprocess(np.zeros((100, 100, 3), dtype=np.uint8), settings)
    assert out.shape == (32, 64, 3)
