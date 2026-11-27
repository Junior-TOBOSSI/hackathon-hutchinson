"""DBX-04-FINAL: presse-5s preparation plan, on an archive built in memory (no real image)."""

import io
import zipfile

import pytest

from mlops.datasets_prep import presse_5s


def archive(tmp_path, rows, extra=None):
    path = tmp_path / "presse.zip"
    with zipfile.ZipFile(path, "w") as z:
        lines = ["filename,label,notes,source"]
        for i, (name, label, source) in enumerate(rows):
            z.writestr(name, f"img-{i}".encode())
            lines.append(f"{name},{label},n,{source}")
        z.writestr("labels.csv", "\n".join(lines))
        z.writestr("reference.png", b"img-0")  # byte-identical to the first image
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


ROWS = [
    ("good/good_001.png", "good", "lot pilote valide"),
    ("anomaly/anomaly_004.png", "zone_person", "lot pilote valide"),
    ("good/good_002.png", "good", "planche generee recadree"),
    ("anomaly/anomaly_007.png", "disorder", "planche generee recadree"),
]


def test_reference_duplicate_is_not_a_sample_and_sources_stay_together(tmp_path):
    plan = presse_5s.build_plan(archive(tmp_path, ROWS))
    assert plan["problems"] == []
    assert len(plan["items"]) == 4 and plan["excluded"][0]["file"] == "reference.png"
    by_source = {}
    for item in plan["items"]:
        by_source.setdefault(item["source"], set()).add(item["split"])
    assert by_source == {"lot pilote valide": {"test"}, "planche generee recadree": {"train"}}
    assert next(i for i in plan["items"] if i["label"] == "zone_person")["possible_person"]


def test_unlabelled_images_and_unknown_labels_are_reported(tmp_path):
    rows = [*ROWS, ("anomaly/x.png", "mystery", "lot pilote valide")]
    plan = presse_5s.build_plan(archive(tmp_path, rows, extra={"anomaly/orphan.png": b"z"}))
    assert any("unknown label" in p for p in plan["problems"])
    assert any("without label" in p for p in plan["problems"])


def test_import_requires_explicit_authorization(monkeypatch):
    monkeypatch.setattr("sys.argv", ["presse_5s", "import", "--zip", "x.zip"])
    with pytest.raises(SystemExit, match="authorization"):
        presse_5s.main()


def test_zip_io_helper():
    assert presse_5s.sha256(io.BytesIO(b"a").getvalue()) == presse_5s.sha256(b"a")
