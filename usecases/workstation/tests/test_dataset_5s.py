"""Test on the REAL dataset (dataset_5S_80_496x325), when it is present.

The images are never versioned: this test is SKIPPED in CI and on a machine without them.
Put the dataset in data/raw/workstation/ (or set WORKSTATION_DATA_ROOT to the folder
holding raw/, e.g. ~/data on the cluster).

Cross-validated measure (see evaluate.py): at least 95 % of the anomalies raise an alert,
at most 10 % of the conforming photos do. Reference comparison only (no detector).
"""

import os
from pathlib import Path

import pytest

from usecases.workstation.detector import REPO_ROOT
from usecases.workstation.evaluate import evaluate, summary
from usecases.workstation.station import load_station

DATA_ROOT = Path(os.environ.get("WORKSTATION_DATA_ROOT", REPO_ROOT / "data")).expanduser()


def test_dataset_5s_cross_validated():
    station = load_station("dataset_5s", DATA_ROOT)
    if not (station["dataset_dir"] / "labels.csv").exists():
        pytest.skip(f"dataset_5S not available in {DATA_ROOT}")
    rows, _ = evaluate(station, {"detector": "none"}, folds=5)
    print("\n" + summary(rows))
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    assert sum(r["decision"] != "conforme" for r in alerts) / len(alerts) >= 0.95, summary(rows)
    assert sum(r["decision"] != "conforme" for r in normal) / len(normal) <= 0.10, summary(rows)
    assert not any(r["alignment_failed"] for r in rows)
