"""Test on the REAL dataset (presse_5S_20), when it is present.

The images are never versioned: this test is SKIPPED in CI and on a machine without them.
Put the dataset in data/raw/workstation/ (or set WORKSTATION_DATA_ROOT to the folder
holding raw/, e.g. ~/data on the cluster).

20 photos only: this checks that the chain works on every kind of anomaly, it is not a
performance benchmark. Leave-one-out on the conforming photos, comparison only (no
detector, so that the test stays fast).
"""

import os
from pathlib import Path

import pytest

from usecases.workstation.detector import REPO_ROOT
from usecases.workstation.evaluate import evaluate, summary
from usecases.workstation.station import load_station

DATA_ROOT = Path(os.environ.get("WORKSTATION_DATA_ROOT", REPO_ROOT / "data")).expanduser()


def test_presse_5s_every_anomaly_kind_is_caught():
    station = load_station("presse_5s", DATA_ROOT)
    if not (station["dataset_dir"] / "labels.csv").exists():
        pytest.skip(f"presse_5S_20 not available in {DATA_ROOT}")
    rows, _ = evaluate(station, {"detector": "none"}, folds=5)
    print("\n" + summary(rows))
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    assert {r["type"] for r in alerts} == {"disorder", "zone_object", "zone_person"}
    assert sum(r["right_reason"] for r in alerts) / len(alerts) >= 0.9, summary(rows)
    assert sum(r["decision"] != "conforme" for r in normal) <= 1, summary(rows)
    assert not any(r["alignment_failed"] for r in rows)
