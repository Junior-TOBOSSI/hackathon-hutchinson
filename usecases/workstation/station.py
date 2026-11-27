"""Read a station file (``stations/<name>.yaml``): reference views, boxes, normal photos.

A station file is the single source of truth for one workstation:
- ``views``: one entry per camera framing, each with its reference image, its zones
  (``empty_zones``: nothing may appear there) and its slots (``element_slots``);
- ``dataset`` / ``normal_images``: the labelled photos and the conforming ones used to
  learn what "normal" looks like (normal.py);
- ``exclude_from_eval``: photos used as references, never used to measure.

Paths in the file are relative to a data root (``data`` on the PC, ``~/data`` on the
cluster): images are never versioned.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from usecases.workstation.zones import validate_polygon

STATIONS_DIR = Path(__file__).parent / "stations"


def station_path(name_or_path: str) -> Path:
    path = Path(name_or_path).expanduser()
    return path if path.suffix in (".yaml", ".yml") else STATIONS_DIR / f"{name_or_path}.yaml"


def load_station(name_or_path: str, data_root: str | Path = "data") -> dict[str, Any]:
    """The station with validated polygons and ABSOLUTE image paths."""
    root = Path(data_root).expanduser().resolve()
    station = yaml.safe_load(station_path(name_or_path).read_text(encoding="utf-8"))
    station["data_root"] = root
    for view in station["views"]:
        view["reference_image"] = str(root / view["reference_image"])
        for kind in ("empty_zones", "element_slots"):
            view[kind] = {n: validate_polygon(n, p) for n, p in (view.get(kind) or {}).items()}
    if "dataset" in station:
        station["dataset_dir"] = root / station["dataset"]
    return station


def labelled_photos(station: dict[str, Any]) -> list[dict[str, str]]:
    """Rows of the dataset's labels.csv, without the photos used as references.

    Empty when the dataset is not on this machine (e.g. CI): the analyzer then simply
    has no normal model and compares with the reference images."""
    labels = station.get("dataset_dir", Path("/nonexistent")) / "labels.csv"
    if not labels.exists():
        return []
    with labels.open(encoding="utf-8") as f:
        rows = [_normalize(r, station.get("labels") or {}) for r in csv.DictReader(f)]
    excluded = set(station.get("exclude_from_eval") or [])
    return [r for r in rows if r["filename"] not in excluded and r["label"] != "reference"]


def _normalize(row: dict[str, str], columns: dict[str, str]) -> dict[str, str]:
    """Common fields ``filename``, ``label`` and ``kind`` (good or the anomaly type),
    whatever the labels.csv layout. ``columns`` (station ``labels``) names the columns
    holding the file, the class and the anomaly type; without it, the usual names are
    tried (filename / label / anomaly_type_indicative)."""
    filename = row.get(columns.get("file", "filename")) or row.get("filename") or ""
    label = (row.get(columns.get("label", "label")) or "").strip()
    anomaly = (row.get(columns.get("type", "anomaly_type_indicative")) or "").strip()
    if label == "good":
        kind = "good"
    elif label == "reference":
        kind = "reference"
    else:
        kind = anomaly if anomaly and anomaly not in ("none", "aucune") else label
    return {**row, "filename": filename.strip(), "label": label, "kind": kind}


def normal_photos(station: dict[str, Any]) -> list[str]:
    """Absolute paths of the conforming photos (label "good"), references excluded."""
    return [
        str(station["dataset_dir"] / r["filename"])
        for r in labelled_photos(station)
        if r["kind"] == "good"
    ]


def analyzer_params(station: dict[str, Any], normal_images: list[str] | None = None) -> dict:
    """The analyzer parameters that describe this station."""
    return {
        "views": [
            {
                "name": v["name"],
                "reference_image": v["reference_image"],
                "empty_zones": v["empty_zones"],
                "element_slots": v["element_slots"],
            }
            for v in station["views"]
        ],
        "normal_images": normal_photos(station) if normal_images is None else normal_images,
        **(station.get("params") or {}),  # section-specific settings (e.g. allowed persons)
    }
