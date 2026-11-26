"""Tests on the REAL station images (poste1, poste2), when they are present.

The images are never versioned: these tests are SKIPPED in CI and on a machine without
them. Put the raw images in data/raw/workstation/ (or set WORKSTATION_DATA_ROOT to the
folder holding raw/ and processed/, e.g. ~/data on the cluster).

What they check, for each station: the reference can be built, generated variants are
analyzed with at least 85 % of the expected alerts raised and no more than 10 % false
alarms (on a fresh random seed, with no detector: the reference comparison alone).
"""

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from usecases.workstation.detector import REPO_ROOT
from usecases.workstation.evaluate import analyzer_for, evaluate, summary
from usecases.workstation.make_variants import generate, load_station, prepare_reference, write

DATA_ROOT = Path(os.environ.get("WORKSTATION_DATA_ROOT", REPO_ROOT / "data")).expanduser()


@pytest.mark.parametrize("name", ["poste1", "poste2"])
def test_real_station(name, tmp_path):
    station = load_station(name)
    if not (DATA_ROOT / station["source"]).exists():
        pytest.skip(f"raw image of {name} not available in {DATA_ROOT}")

    reference_path = prepare_reference(station, DATA_ROOT)
    reference = cv2.imread(str(reference_path))
    variants = generate(reference, station, np.random.default_rng(1234), n=6)
    write(variants, tmp_path)

    analyzer, thresholds = analyzer_for(station, reference_path, {"detector": "none"})
    rows = evaluate(analyzer, thresholds, tmp_path)
    print(f"\n{name}\n{summary(rows)}")

    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    detection = sum(r["decision"] != "conforme" for r in alerts) / len(alerts)
    false_alarms = sum(r["decision"] != "conforme" for r in normal) / len(normal)
    assert detection >= 0.85, summary(rows)
    assert false_alarms <= 0.10, summary(rows)
