"""Scientific handoff checks without datasets, models or remote Databricks mutations."""

from __future__ import annotations

import hashlib

import pytest

from mlops.pipelines.workstation.run_pipeline import SECTIONS, materialize
from mlops.training.checks import effective_parameters
from mlops.training.service import TrainingService
from mlops.training.specs import load_specs, view


def test_binary_and_workstation_are_distinct_real_pipelines():
    specs = {spec.id: spec for spec in load_specs()}
    binary = specs["quality-industrial-binary"]
    workstation = specs["workstation-industrial"]
    assert binary.classes == ["OK", "NOK"]
    assert binary.dataset.families == ["quality-industrial-binary"]
    assert workstation.classes == ["good", "anomaly"]
    assert set(workstation.param("station").choices) == set(SECTIONS)
    assert view(binary, set()).requirements[0].ok
    assert view(workstation, set()).requirements[0].ok
    assert not view(binary, set()).executable  # job not created
    assert not view(workstation, set()).executable
    _, checks = effective_parameters(workstation, {"station": "unknown"})
    assert any(check.status == "error" for check in checks)


def test_workstation_materialization_rejects_wrong_section_and_changed_file(tmp_path):
    folder = tmp_path / "published/raw/workstation/poste_5s_11"
    folder.mkdir(parents=True)
    contents = {
        "reference.png": b"reference",
        "labels.csv": (
            b"file,label,intended_anomaly\n"
            b"good.png,good,none\n"
            b"bad.png,anomaly,disorder\n"
        ),
        "good.png": b"good",
        "bad.png": b"anomaly",
    }
    for name, data in contents.items():
        (folder / name).write_bytes(data)
    def entry(name):
        return {
            "file": f"raw/workstation/poste_5s_11/{name}",
            "sha256": hashlib.sha256(contents[name]).hexdigest(),
        }
    manifest = {
        "dataset_id": "poste-5s-11",
        "station": "press_cell",
        "classes": ["good", "anomaly"],
        "items": [entry("good.png") | {"label": "good"}, entry("bad.png") | {"label": "anomaly"}],
        "assets": [entry("reference.png"), entry("labels.csv")],
    }
    target = tmp_path / "isolated"
    assert materialize(manifest, tmp_path / "published", target, "press_cell") == {
        "good": 1,
        "anomaly": 1,
    }
    assert materialize(manifest, tmp_path / "published", target, "press_cell") == {
        "good": 1,
        "anomaly": 1,
    }  # retry checks existing bytes
    with pytest.raises(ValueError, match="family/section"):
        materialize(manifest, tmp_path / "published", tmp_path / "other", "machine_cell")
    (folder / "good.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed workstation file"):
        materialize(manifest, tmp_path / "published", target, "press_cell")


def test_workstation_group_results_are_visible_in_training_factory(monkeypatch):
    csv_data = (
        b"file,type,expected,decision,score,correct,right_reason,named_person,view,"
        b"alignment_failed,found,latency_ms\n"
        b"good.png,good,conforme,conforme,0.1,True,False,False,front,False,,12.5\n"
        b"bad.png,disorder,anomalie,anomalie,0.9,True,True,False,front,False,tool,15.0\n"
    )
    service = TrainingService.__new__(TrainingService)
    monkeypatch.setattr(
        service,
        "_artifact",
        lambda _id, path: csv_data if path == "evaluation/results.csv" else None,
    )
    evaluation = service.evaluation("run-1")
    assert evaluation["kind"] == "workstation"
    assert evaluation["matrix"]["good"]["good"] == 1
    assert evaluation["matrix"]["anomaly"]["anomaly"] == 1
    page = service.predictions("run-1", "poste-5s-11", "group-v1", {"true": "anomaly"}, 0, 24)
    assert page["total"] == 1
    assert page["items"][0]["right_reason"]
    assert page["items"][0]["annotated_path"] == "evaluation/annotated/bad.png"
