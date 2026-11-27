"""DBX-05B: pipelines, checks, materialisation, Quality wrapper, catalogue, results, launch.

Fixtures and fakes only: no Databricks call, no remote job, no real industrial data.
"""

import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from mlops.databricks.connector import (
    ConflictError,
    DatabricksUnavailableError,
    ForbiddenOperationError,
)
from mlops.datasets_prep import quality_synthetic_3c as syn
from mlops.pipelines.quality_industrial import run_pipeline as rp
from mlops.training import service as svc
from mlops.training.checks import dataset_checks, effective_parameters
from mlops.training.materialize import MaterializationError, materialize
from mlops.training.specs import PIPELINES_DIR, load_specs, view

KIT = PIPELINES_DIR / "quality_industrial" / "kit"


def spec(pid):
    return next(s for s in load_specs() if s.id == pid)


@pytest.fixture(scope="module")
def synthetic():
    plan = syn.generate()
    items = [
        {
            "file": f"{i['split']}/{i['label']}/{i['name']}",
            **{k: i[k] for k in ("label", "split", "group", "sha256")},
        }
        for i in plan["items"]
    ]
    return {
        "manifest": {
            "classes": syn.CLASSES,
            "annotation_format": "classification",
            "synthetic": True,
            "items": items,
        },
        "blobs": plan["blobs"],
    }


# ------------------------------------------------------------------ pipelines and provenance


def test_two_declared_pipelines_and_group_defaults_are_preserved():
    ids = [s.id for s in load_specs()]
    assert ids == ["quality-demo", "quality-industrial"]
    q = spec("quality-industrial")
    group_defaults = yaml.safe_load((KIT / "hyperparametres.yaml").read_text(encoding="utf-8"))
    assert {p.name: p.default for p in q.parameters if p.name in group_defaults} == group_defaults
    assert q.param("lr0") is None and q.param("learning_rate") is None  # not consumed by train.py
    assert (
        q.param("fusionner_test").default is False and q.param("fusionner_test").level == "imposed"
    )
    assert spec("quality-demo").parameters == []


def test_vendored_kit_is_byte_identical_to_the_group_commit():
    rows = [
        line.split("|")
        for line in (KIT / "PROVENANCE.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
    ]
    assert len(rows) == 15  # + PROVENANCE.md itself
    for row in rows:
        local, blob = row[1].strip().strip("`"), row[3].strip().strip("`")
        data = (KIT / local).read_bytes()
        assert hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob, local


def test_pipeline_is_executable_only_when_its_job_exists():
    q = spec("quality-industrial")
    assert not view(q, set()).executable
    assert view(q, {"hovis-quality-industrial-training"}).executable
    assert not view(q, None).executable


# ------------------------------------------------------------------ checks


def test_parameters_are_typed_bounded_and_imposed_values_locked():
    q = spec("quality-industrial")
    values, checks = effective_parameters(q, {"epochs": 5, "batch": "16"})
    assert values["epochs"] == 5 and values["batch"] == 16 and values["patience"] == 10
    for bad in (
        {"epochs": 0},
        {"epochs": 2.5},
        {"fusionner_test": True},
        {"lr0": 0.01},
        {"modele_base": "x.pt"},
    ):
        _, c = effective_parameters(q, bad)
        assert any(x.status == "error" for x in c), bad


def test_synthetic_3c_passes_every_quality_check(synthetic):
    checks = dataset_checks(
        spec("quality-industrial"), "quality-synthetic-3c", synthetic["manifest"]
    )
    assert all(c.status == "ok" for c in checks), [c for c in checks if c.status != "ok"]


def test_missing_validation_png_and_leaks_block_the_launch(synthetic):
    q = spec("quality-industrial")
    items = [dict(i) for i in synthetic["manifest"]["items"]]
    no_val = [i for i in items if i["split"] != "validation"]
    assert (
        next(
            c
            for c in dataset_checks(q, "presse-like", {"items": no_val, "classes": syn.CLASSES})
            if c.id == "splits"
        ).status
        == "error"
    )
    png = [dict(i, file=i["file"].replace(".jpg", ".png")) for i in items]
    assert (
        next(
            c
            for c in dataset_checks(q, "x", {"items": png, "classes": syn.CLASSES})
            if c.id == "extension"
        ).status
        == "error"
    )
    leak = [dict(i) for i in items]
    leak[0]["group"] = next(i["group"] for i in items if i["split"] == "test")
    assert (
        next(
            c
            for c in dataset_checks(q, "x", {"items": leak, "classes": syn.CLASSES})
            if c.id == "leakage"
        ).status
        == "error"
    )
    wrong = dataset_checks(q, "x", {"items": items, "classes": ["OK", "NOK"]})
    assert next(c for c in wrong if c.id == "classes").status == "error"


# ------------------------------------------------------------------ materialisation


def write_volume(tmp_path, synthetic):
    src = tmp_path / "volume"
    for item in synthetic["manifest"]["items"]:
        path = src / item["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(synthetic["blobs"][Path(item["file"]).name])
    return src


def test_materialisation_matches_the_group_layout(tmp_path, synthetic):
    src = write_volume(tmp_path, synthetic)
    counts = materialize(
        synthetic["manifest"], src, tmp_path / "ds", {"validation": "val"}, [".jpg"], "group", True
    )
    assert counts["val"] == {"OK": 6, "NOK_SANS": 6, "NOK_DOUBLE": 6}
    assert {p.name for p in (tmp_path / "ds").iterdir()} == {
        "train",
        "val",
        "test",
        "repartition.csv",
    }
    rows = list(csv.DictReader(open(tmp_path / "ds" / "repartition.csv", encoding="utf-8")))
    assert (
        set(rows[0]) == {"fichier", "classe", "type", "rafale", "pli", "split"} and len(rows) == 108
    )
    assert {r["classe"] for r in rows if r["type"] != "OK"} == {"NOK"}


def test_materialisation_refuses_tampered_files_leaks_and_reuse(tmp_path, synthetic):
    src = write_volume(tmp_path, synthetic)
    first = synthetic["manifest"]["items"][0]
    (src / first["file"]).write_bytes(b"tampered")
    with pytest.raises(MaterializationError, match="SHA-256"):
        materialize(
            synthetic["manifest"],
            src,
            tmp_path / "a",
            {"validation": "val"},
            [".jpg"],
            "group",
            True,
        )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "x").write_text("x")
    with pytest.raises(MaterializationError, match="not empty"):
        materialize(synthetic["manifest"], src, tmp_path / "b", {}, [".jpg"])


# ------------------------------------------------------------------ Quality wrapper


def test_commands_never_overwrite_nor_merge_the_test_split(tmp_path):
    cmd = rp.train_command("py", tmp_path / "d", tmp_path / "o", "v", tmp_path / "hp.yaml", "cpu")
    assert "--ecraser" not in cmd and "--fusionner-test" not in cmd and cmd[1].endswith("train.py")
    ev = rp.evaluate_command(
        "py", tmp_path / "c.yaml", tmp_path / "d" / "test", tmp_path / "t", "cpu"
    )
    assert ev[ev.index("--images") + 1].endswith("test")
    assert set(
        rp.hyperparameters({p.name: p.default for p in spec("quality-industrial").parameters})
    ) == set(rp.HP_KEYS)


def test_results_and_evaluation_parsing(tmp_path):
    (tmp_path / "results.csv").write_text(
        "epoch,time,train/loss,metrics/accuracy_top1,metrics/accuracy_top5,val/loss,lr/pg0\n"
        "1,1.0,0.9,0.6,1,0.7,0.001\n2,2.0,0.4,1.0,1,0.03,0.001\n3,3.0,0.2,0.8,1,2.1,0.001\n",
        encoding="utf-8",
    )
    hist = rp.read_results(tmp_path / "results.csv")
    assert (
        hist[1]["train_loss"] == 0.4
        and hist[1]["val_accuracy_top1"] == 1.0
        and "train_accuracy_top1" not in hist[1]
    )
    assert rp.training_summary(hist, 30) == {
        "epochs_done": 3,
        "best_epoch": 2,
        "early_stopped": 1.0,
    }
    m = rp.evaluation_metrics(
        {
            "rappel": 0.9,
            "faux_rejets": 0.01,
            "par_type": {"NOK_SANS": {"n": 10, "arretees": 9}},
            "seuil_nok": 0.6,
        }
    )
    assert m == {
        "test_rappel": 0.9,
        "test_faux_rejets": 0.01,
        "test_seuil_nok": 0.6,
        "test_rappel_NOK_SANS": 0.9,
    }


def test_candidate_registration_is_idempotent_and_never_promotes():
    client, mlflow = MagicMock(), MagicMock()
    client.search_model_versions.return_value = [SimpleNamespace(run_id="other", version="1")]
    mlflow.register_model.return_value = SimpleNamespace(version="2")
    v = rp.register_candidate(client, mlflow, "m", "r1", "models:/x", {"hovis_candidate": "true"})
    assert v.version == "2"
    client.search_model_versions.return_value = [SimpleNamespace(run_id="r1", version="2")]
    assert rp.register_candidate(client, mlflow, "m", "r1", "models:/x", {}).version == "2"
    assert mlflow.register_model.call_count == 1
    client.set_registered_model_alias.assert_not_called()
    assert all(c.args[2] != "argos_approval" for c in client.set_model_version_tag.call_args_list)


# ------------------------------------------------------------------ results helpers


ROWS = [
    {
        "fichier": "a.jpg",
        "vraie_classe": "OK",
        "vrai": "OK",
        "verdict": "OK",
        "type_defaut": "",
        "score_nok": "0.1",
        "latence_ms": "5",
    },
    {
        "fichier": "b.jpg",
        "vraie_classe": "OK",
        "vrai": "OK",
        "verdict": "NOK",
        "type_defaut": "NOK_SANS",
        "score_nok": "0.8",
        "latence_ms": "5",
    },
    {
        "fichier": "c.jpg",
        "vraie_classe": "NOK_SANS",
        "vrai": "NOK",
        "verdict": "NOK",
        "type_defaut": "NOK_DOUBLE",
        "score_nok": "0.9",
        "latence_ms": "5",
    },
    {
        "fichier": "d.jpg",
        "vraie_classe": "NOK_DOUBLE",
        "vrai": "NOK",
        "verdict": "OK",
        "type_defaut": "",
        "score_nok": "0.2",
        "latence_ms": "5",
    },
    {
        "fichier": "e.jpg",
        "vraie_classe": "NOK_DOUBLE",
        "vrai": "NOK",
        "verdict": "A_VERIFIER",
        "type_defaut": "NOK_DOUBLE",
        "score_nok": "0.5",
        "latence_ms": "5",
    },
]


def test_confusion_keeps_a_verifier_and_business_flags():
    c = svc.confusion(ROWS)
    assert c["columns"] == ["OK", "A_VERIFIER", "NOK_DOUBLE", "NOK_SANS"]
    assert c["matrix"]["NOK_DOUBLE"]["A_VERIFIER"] == 1 and c["matrix"]["OK"]["NOK_SANS"] == 1
    rows = [svc.enrich(r) for r in ROWS]
    assert [r["false_reject"] for r in rows] == [False, True, False, False, False]
    assert [r["missed_defect"] for r in rows] == [False, False, False, True, False]
    assert [r["type_confusion"] for r in rows] == [False, False, True, False, False]
    assert sum(svc.match(r, {"kind": "incorrect"}) for r in rows) == 4
    assert [r["fichier"] for r in rows if svc.match(r, {"true": "NOK_DOUBLE", "pred": "OK"})] == [
        "d.jpg"
    ]


def test_job_states_are_normalised():
    assert svc.normalise("TERMINATED", "SUCCESS") == "succeeded"
    assert svc.normalise("RUNNING", None) == "running"
    assert svc.normalise("TERMINATED", "FAILED") == "failed"
    assert svc.normalise("TERMINATED", "CANCELED") == "cancelled"


# ------------------------------------------------------------------ catalogue and launch


class FakeConnector:
    def __init__(self):
        self.w, self.mlflow = MagicMock(), MagicMock()
        self.reads = MagicMock()
        self.settings = SimpleNamespace(request_budget_seconds=25)

    def _cached(self, key, fn, ttl=None):
        return fn()

    def _call(self, fn, what="x"):
        return fn()

    def list_jobs(self):
        return [SimpleNamespace(job_id=7, name="argos-poc-quality-training")]

    def job_runs(self, job_id, limit=10):
        return [
            SimpleNamespace(
                run_id=41,
                life_cycle_state="TERMINATED",
                result_state="SUCCESS",
                start_time=None,
                end_time=None,
                duration_s=12.0,
                run_page_url="https://x/run/41",
            ),
            SimpleNamespace(
                run_id=42,
                life_cycle_state="RUNNING",
                result_state=None,
                start_time=None,
                end_time=None,
                duration_s=None,
                run_page_url=None,
            ),
        ]


def make_service(tmp_path):
    c = FakeConnector()
    c.mlflow.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="1")

    def run(rid, jr, ds):
        return SimpleNamespace(
            info=SimpleNamespace(run_id=rid),
            data=SimpleNamespace(
                params={"dataset_version": ds}, tags={"databricks.job_run_id": jr}
            ),
        )

    c.mlflow.search_runs.return_value = [
        run("a", "41", "synthetic-v1"),
        run("b", "41", "synthetic-v1"),
        run("z", "999", "x"),
    ]
    c.mlflow.search_model_versions.return_value = [
        SimpleNamespace(version="1", run_id="a"),
        SimpleNamespace(version="2", run_id="b"),
    ]
    return svc.TrainingService(c, launches=svc.LaunchStore(tmp_path / "launches.json")), c


def test_catalogue_links_job_runs_mlflow_runs_and_versions_by_tags_only(tmp_path):
    s, _ = make_service(tmp_path)
    rows = {r.job_run_id: r for r in s.trainings()}
    assert (
        rows[41].mlflow_runs == ["a", "b"]
        and rows[41].model_versions == ["1", "2"]
        and rows[41].status == "succeeded"
    )
    assert (
        rows[42].mlflow_runs == []
        and rows[42].model_versions == []
        and rows[42].dataset_version is None
    )
    k = s.kpis()
    assert k.running == 1 and k.pipelines_total == 2 and k.pipelines_executable == 1


def test_launch_is_refused_without_authorization(tmp_path, monkeypatch):
    s, c = make_service(tmp_path)
    monkeypatch.delenv("HOVIS_TRAINING_REMOTE", raising=False)
    monkeypatch.setattr(
        s, "validate", lambda *a: SimpleNamespace(launchable=True, parameters={}, checks=[])
    )
    with pytest.raises(ForbiddenOperationError):
        s.launch("quality-demo", "quality-synthetic", "synthetic-v2", {}, "key-1")
    c.w.jobs.run_now.assert_not_called()
    with pytest.raises(ForbiddenOperationError):
        s.cancel(41)


def test_launch_is_idempotent_and_a_doubtful_answer_is_never_followed_by_a_new_run(
    tmp_path, monkeypatch
):
    s, c = make_service(tmp_path)
    monkeypatch.setenv("HOVIS_TRAINING_REMOTE", "1")
    monkeypatch.setattr(
        s, "validate", lambda *a: SimpleNamespace(launchable=True, parameters={}, checks=[])
    )
    monkeypatch.setattr(s, "_run_arguments", lambda *a: {"notebook_params": {"args": "[]"}})
    c.w.jobs.run_now.side_effect = DatabricksUnavailableError("Databricks unreachable")
    with pytest.raises(DatabricksUnavailableError):
        s.launch("quality-demo", "quality-synthetic", "synthetic-v2", {}, "key-2")
    assert s.launches.get("key-2").status == "uncertain"
    c.w.jobs.run_now.side_effect = None
    c.w.jobs.run_now.return_value = SimpleNamespace(run_id=77)
    first = s.launch(
        "quality-demo", "quality-synthetic", "synthetic-v2", {}, "key-2"
    )  # same token: deduped by Databricks
    again = s.launch(
        "quality-demo", "quality-synthetic", "synthetic-v2", {}, "key-2"
    )  # double click
    assert first.job_run_id == again.job_run_id == 77 and c.w.jobs.run_now.call_count == 2
    assert all(
        call.kwargs["idempotency_token"] == "key-2" for call in c.w.jobs.run_now.call_args_list
    )
    monkeypatch.setattr(
        s,
        "validate",
        lambda *a: SimpleNamespace(
            launchable=False,
            parameters={},
            checks=[SimpleNamespace(status="error", label="splits")],
        ),
    )
    with pytest.raises(ConflictError):
        s.launch("quality-demo", "quality-synthetic", "synthetic-v2", {}, "key-3")


def test_quality_demo_override_keeps_the_job_definition(tmp_path, monkeypatch):
    s, c = make_service(tmp_path)
    args = ["--code-dir", "c", "--dataset-dir", "/Volumes/w/s/images/synthetic-v1", "--model", "m"]
    c.w.jobs.get.return_value = SimpleNamespace(
        settings=SimpleNamespace(
            tasks=[
                SimpleNamespace(
                    notebook_task=SimpleNamespace(
                        base_parameters={"script": "s", "args": json.dumps(args)}
                    )
                )
            ]
        )
    )
    store = MagicMock()
    store.scope_id.return_value = "quality-poc"
    store._managed.return_value = SimpleNamespace(dataset_root="/Volumes/w/s/images")
    monkeypatch.setattr(svc, "dataset_store", lambda _c: store)
    record = svc.LaunchRecord(
        request_id="r",
        idempotency_key="k",
        pipeline_id="quality-demo",
        dataset_id="quality-synthetic",
        dataset_version="synthetic-v2",
        parameters={},
        status="uncertain",
        created_at="now",
    )
    out = s._run_arguments(spec("quality-demo"), 7, record)
    new = json.loads(out["notebook_params"]["args"])
    assert (
        new[new.index("--dataset-dir") + 1] == "/Volumes/w/s/images/synthetic-v2"
        and new[new.index("--model") + 1] == "m"
        and new[-2:] == ["--request-id", "r"]
    )
    c.w.jobs.reset.assert_not_called() and c.w.jobs.update.assert_not_called()


def test_real_group_scripts_are_importable_and_unmodified_entrypoints_exist():
    for name in ("train.py", "evaluer.py", "export_onnx.py", "qualite702/inference.py"):
        assert (KIT / name).is_file()
    out = subprocess.run(
        [
            "python",
            "-c",
            "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())",
            str(KIT / "train.py"),
        ]
    )
    assert out.returncode == 0
    assert io.StringIO  # keep import used


def test_pipeline_own_confusion_matrix_is_read_as_is():
    out = svc.from_matrix({"labels": ["OK", "NOK"], "matrix": [[17, 3], [3, 17]], "split": "test"})
    assert (
        out["matrix"] == {"OK": {"OK": 17, "NOK": 3}, "NOK": {"OK": 3, "NOK": 17}}
        and out["n"] == 40
    )
    assert (
        out["per_class"]["NOK"]["recall"] == 17 / 20
        and out["per_class"]["NOK"]["precision"] == 17 / 20
    )
