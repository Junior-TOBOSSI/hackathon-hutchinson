"""SCI-03: staging of the group's Workstation datasets (relative paths, assets, provenance).

Tiny fake files only: no image of the group is used by these tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlops.datasets_prep import workstation_group as wg
from mlops.pipelines.workstation.run_pipeline import materialize


def group_folder(root: Path, rows: list[str], readme: bool = True) -> Path:
    folder = root / "poste_5s_11"
    for sub in ("good", "anomaly"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "reference.png").write_bytes(b"reference")
    for i in range(1, 6):
        (folder / "good" / f"good_0{i}.png").write_bytes(f"good{i}".encode())
        (folder / "anomaly" / f"anomaly_0{i}.png").write_bytes(f"anomaly{i}".encode())
    (folder / "labels.csv").write_text(
        "file,label,intended_anomaly\nreference.png,reference,none\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    if readme:
        (folder / "README.txt").write_text("Lot pilote synthetique.", encoding="utf-8")
    return root


GROUP_ROWS = [f"good/good_0{i}.png,good,none" for i in range(1, 6)] + [
    f"anomaly/anomaly_0{i}.png,anomaly,disorder" for i in range(1, 6)
]


@pytest.fixture
def outside(tmp_path, monkeypatch):
    # staging is refused inside the repository: tmp_path is outside it
    return tmp_path


def test_relative_group_paths_are_staged_with_their_tree(outside):
    source = group_folder(outside / "raw", GROUP_ROWS)
    version = wg.stage("press_cell", source, outside / "staged")
    m = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    files = {i["file"] for i in m["items"]}
    assert "raw/workstation/poste_5s_11/good/good_01.png" in files
    assert (version / "raw/workstation/poste_5s_11/anomaly/anomaly_05.png").is_file()
    assert {a["role"] for a in m["assets"]} == {"reference", "labels", "readme"}
    assert m["image_provenance"] == "synthetic" and m["synthetic"] is True
    assert all(i["provenance"] == "synthetic" for i in m["items"])
    assert m["counts"]["train"] == {"good": 5, "anomaly": 0}
    # the pipeline materializes exactly what was staged (SHA-256 checked file by file)
    assert materialize(m, version, outside / "work", "press_cell") == {"good": 5, "anomaly": 5}


@pytest.mark.parametrize(
    "bad",
    [
        "../poste_bleu_5s_11/good/good_01.png",
        "good/../../x.png",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "good\\good_01.png",
        "./good/good_01.png",
    ],
)
def test_path_traversal_and_odd_paths_are_refused(outside, bad):
    rows = [bad + ",good,none", *GROUP_ROWS[1:]]
    source = group_folder(outside / "raw", rows)
    with pytest.raises(ValueError, match="unsafe|escapes"):
        wg.stage("press_cell", source, outside / "staged")


def test_counts_and_repository_guard(outside):
    source = group_folder(outside / "raw", GROUP_ROWS[:-1])  # 4 anomalies only
    with pytest.raises(ValueError, match="five good and five anomaly"):
        wg.stage("press_cell", source, outside / "staged")
    repo = Path(wg.__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="outside the Git repository"):
        wg.stage("press_cell", group_folder(outside / "raw2", GROUP_ROWS), repo / "var" / "x")


def test_readme_is_optional(outside):
    source = group_folder(outside / "raw", GROUP_ROWS, readme=False)
    m = json.loads(
        (wg.stage("press_cell", source, outside / "staged") / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert {a["role"] for a in m["assets"]} == {"reference", "labels"}
