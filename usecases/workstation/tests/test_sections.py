"""Tests on the REAL section datasets (poste_*_5s_11), when they are present.

The images are never versioned: each section is SKIPPED in CI and on a machine without
its dataset. Put the datasets in data/raw/workstation/ (or set WORKSTATION_DATA_ROOT to
the folder holding raw/, e.g. ~/data on the cluster).

10 photos per section: this checks that the chain still works on each workstation, it is
not a performance benchmark. Leave-one-out on the conforming photos, with the configured
detector (YOLO26): the electrical bench NEEDS it to recognise the operator, who is allowed.
Known dataset issues are allowed (one miss or one false alarm per section at most).
"""

import os
from pathlib import Path

import pytest

from usecases.workstation.detector import REPO_ROOT
from usecases.workstation.evaluate import evaluate, summary
from usecases.workstation.station import load_station

DATA_ROOT = Path(os.environ.get("WORKSTATION_DATA_ROOT", REPO_ROOT / "data")).expanduser()
SECTIONS = ["press_cell", "machine_cell", "machine_cell_variant", "electrical_bench"]


@pytest.mark.parametrize("name", SECTIONS)
def test_section(name):
    station = load_station(name, DATA_ROOT)
    if not (station["dataset_dir"] / "labels.csv").exists():
        pytest.skip(f"dataset of {name} not available in {DATA_ROOT}")
    rows, _ = evaluate(station, {}, folds=5)
    print(f"\n{name}\n{summary(rows)}")
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    assert sum(r["decision"] == "conforme" for r in alerts) <= 1, summary(rows)
    assert sum(r["decision"] != "conforme" for r in normal) <= 1, summary(rows)
    assert not any(r["alignment_failed"] for r in rows)
