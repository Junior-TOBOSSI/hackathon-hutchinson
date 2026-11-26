"""DBX-04: dataset versions, drafts, import and publication over a FAKE Files API.

No Databricks call: an in-memory Volume reproduces the Files API behaviours used
(overwrite=False conflicts, NotFound, directory listing).
"""

import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from mlops.api import routes
from mlops.databricks.connector import ConflictError, DatabricksConnector, ResourceNotFoundError
from mlops.databricks.datasets import (
    InvalidDatasetRequest,
    build_manifest,
    dataset_store,
    manifest_bytes,
    safe_relative_file,
)
from mlops.databricks.settings import DatabricksSettings, ManagedModel

ROOT = "/Volumes/c/s/images"


class NotFound(Exception):
    pass


class AlreadyExists(Exception):
    pass


class FakeFiles:
    """Minimal Files API: files only (directories are implied by paths)."""

    def __init__(self):
        self.data: dict[str, bytes] = {}
        self.writes: list[str] = []
        self.fail_on: str | None = None

    def upload(self, path, stream, overwrite=None):
        if self.fail_on and self.fail_on in path:
            raise ConnectionError("Connection reset")
        if path in self.data and not overwrite:
            raise AlreadyExists(f"ALREADY_EXISTS {path}")
        self.data[path] = stream.read()
        self.writes.append(path)

    def download(self, path):
        if path not in self.data:
            raise NotFound(f"{path} does not exist")
        return SimpleNamespace(contents=io.BytesIO(self.data[path]))

    def get_metadata(self, path):
        if path not in self.data:
            raise NotFound(f"{path} does not exist")
        return SimpleNamespace(content_length=len(self.data[path]))

    def list_directory_contents(self, path):
        prefix = path.rstrip("/") + "/"
        children = {}
        for p in self.data:
            if p.startswith(prefix):
                head, _, rest = p[len(prefix) :].partition("/")
                children[head] = children.get(head, False) or bool(rest)
        if not children:
            raise NotFound(f"{path} does not exist")
        return [
            SimpleNamespace(
                path=prefix + n + ("/" if d else ""),
                is_directory=d,
                last_modified=1_795_000_000_000,
            )
            for n, d in sorted(children.items())
        ]

    def delete(self, path):
        if path not in self.data:
            raise NotFound(path)
        del self.data[path]

    def delete_directory(self, path):
        if any(p.startswith(path.rstrip("/") + "/") for p in self.data):
            raise RuntimeError("DIRECTORY_NOT_EMPTY")


def png(seed: int, size=(16, 16)) -> bytes:
    buf = io.BytesIO()
    Image.new("L", size, seed % 255).save(buf, format="PNG")
    return buf.getvalue()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def seed_v1(files: FakeFiles) -> tuple[str, dict]:
    items = []
    n = 0
    for split in ("train", "validation", "test"):
        for label in ("OK", "NOK"):
            data = png(n)
            name = f"{split}/{label}/{label.lower()}_{n:03d}.png"
            files.data[f"{ROOT}/synthetic-v1/{name}"] = data
            items.append(
                {
                    "file": name,
                    "label": label,
                    "split": split,
                    "sha256": sha(data),
                    "brightness": 0.9,
                    "noise": 5.0,
                    "defect": None,
                }
            )
            n += 1
    manifest = {
        "dataset_version": "synthetic-v1",
        "synthetic": True,
        "generator": "gen.py",
        "seed": 2026,
        "classes": ["OK", "NOK"],
        "split_ratios": {"train": 0.6},
        "items": items,
    }
    raw = json.dumps(manifest, indent=2).encode()
    files.data[f"{ROOT}/synthetic-v1/manifest.json"] = raw
    return sha(raw), manifest


MODEL = ManagedModel(
    id="q",
    display_name="Q",
    use_case="Qualité",
    argos_use_case="quality",
    scope="test",
    uc_name="cat.sch.q",
    training_job="train-q",
    synthetic=True,
    dataset_root=ROOT,
    dataset_name="quality-synthetic",
    dataset_tables=["c.s.annotations"],
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    files = FakeFiles()
    v1_sha, v1 = seed_v1(files)
    w, ml = MagicMock(), MagicMock()
    w.files = files
    ml.get_registered_model.return_value = SimpleNamespace(aliases={"champion": "1"})
    ml.search_model_versions.return_value = [SimpleNamespace(version="1")]
    ml.get_model_version.return_value = SimpleNamespace(
        name="cat.sch.q",
        version="1",
        run_id="r1",
        model_id=None,
        source="s",
        status="READY",
        tags={},
        creation_timestamp=1,
    )
    ml.get_run.return_value = SimpleNamespace(
        info=SimpleNamespace(
            run_id="r1",
            run_name="r1",
            experiment_id="1",
            status="FINISHED",
            start_time=1,
            end_time=2,
            artifact_uri="x",
        ),
        data=SimpleNamespace(params={}, metrics={}, tags={"argos.manifest_sha256": v1_sha}),
    )
    for key in ("DATABRICKS_CONFIG_PROFILE", "MLFLOW_TRACKING_URI", "MLFLOW_REGISTRY_URI"):
        monkeypatch.setenv(key, "x")
    settings = DatabricksSettings(
        models=(MODEL,), extra_triggerable_jobs=(), snapshot_dir=str(tmp_path)
    )
    c = DatabricksConnector(settings, workspace=w, mlflow_client=ml)
    return SimpleNamespace(c=c, files=files, store=dataset_store(c), v1=v1, v1_sha=v1_sha)


def snapshot_v1(files):
    return {p: b for p, b in files.data.items() if "/synthetic-v1/" in p}


# ------------------------------------------------------------------ reads


def test_index_reads_the_manifest_and_links_the_model_versions(env):
    idx = env.store.index("q")
    v1 = idx.versions[0]
    assert v1.version == "synthetic-v1" and v1.ref.manifest_sha256 == env.v1_sha
    assert v1.ref.num_samples == 6 and v1.ref.splits == {"train": 2, "validation": 2, "test": 2}
    assert v1.ref.classes == ["OK", "NOK"] and v1.ref.confidential is False
    assert [u.model_version for u in v1.used_by] == ["1"] and v1.locked
    assert set(v1.split_fingerprints) == {"train", "validation", "test"}


def test_items_are_paginated_filtered_and_capped(env):
    page = env.store.items("q", "synthetic-v1", split="train", limit=1)
    assert page.total == 2 and len(page.items) == 1 and page.facets["split"]["train"] == 2
    assert env.store.items("q", "synthetic-v1", limit=500).limit == 48
    assert env.store.items("q", "synthetic-v1", label="NOK").total == 3


@pytest.mark.parametrize(
    "bad", ["../secret.png", "code/train.py", "runs/1.json", "/abs.png", "a\\b.png", "a/./b.png"]
)
def test_path_traversal_and_reserved_folders_are_refused(env, bad):
    with pytest.raises(InvalidDatasetRequest):
        env.store.image("q", "synthetic-v1", bad)


def test_only_files_listed_in_the_manifest_are_served(env):
    data, media = env.store.image("q", "synthetic-v1", "train/OK/ok_000.png")
    assert media == "image/png" and sha(data) == env.v1["items"][0]["sha256"]
    with pytest.raises(ResourceNotFoundError):
        env.store.image("q", "synthetic-v1", "manifest.json")
    with pytest.raises(InvalidDatasetRequest):
        env.store.image("q", "_drafts", "x.png")


def test_safe_relative_file_normalises():
    assert safe_relative_file("train/OK/a.png") == "train/OK/a.png"


# ------------------------------------------------------------------ drafts


def test_draft_changes_are_validated(env):
    d = env.store.create_draft("q", "synthetic-v1")
    f = "train/OK/ok_000.png"
    with pytest.raises(InvalidDatasetRequest):
        env.store.update_items(
            "q", d["draft_id"], [{"file": f, "action": "relabel", "label": "MAYBE"}]
        )
    with pytest.raises(InvalidDatasetRequest):
        env.store.update_items(
            "q", d["draft_id"], [{"file": f, "action": "relabel", "label": "OK"}]
        )
    with pytest.raises(InvalidDatasetRequest):
        env.store.update_items("q", d["draft_id"], [{"file": "nope.png", "action": "validate"}])
    d = env.store.update_items(
        "q",
        d["draft_id"],
        [{"file": f, "action": "validate"}, {"file": "train/NOK/nok_001.png", "action": "exclude"}],
    )
    assert set(d["changes"]) == {f, "train/NOK/nok_001.png"}
    d = env.store.update_items("q", d["draft_id"], [{"file": f, "action": "reset"}])
    assert set(d["changes"]) == {"train/NOK/nok_001.png"}


def test_import_is_bounded_and_validated(env):
    d = env.store.create_draft("q", "synthetic-v1")
    did = d["draft_id"]
    with pytest.raises(InvalidDatasetRequest):
        env.store.import_files("q", did, [("a.png", io.BytesIO(png(100)))], "OK", "train", False)
    test_image = env.files.data[f"{ROOT}/synthetic-v1/test/OK/ok_004.png"]
    results = env.store.import_files(
        "q",
        did,
        [
            ("good.png", io.BytesIO(png(100))),
            ("same.png", io.BytesIO(png(100))),
            ("text.png", io.BytesIO(b"not an image")),
            ("big.png", io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))),
            ("test-image.png", io.BytesIO(test_image)),  # a test image cannot come back as train
            ("huge.png", io.BytesIO(png(1, size=(4097, 1)))),
        ],
        "OK",
        "train",
        True,
    )
    assert [r.accepted for r in results] == [True, False, False, False, False, False]
    assert "duplicate" in results[4].reason and "4096" in results[5].reason
    too_many = env.store.import_files(
        "q", did, [(f"{i}.png", io.BytesIO(png(200 + i))) for i in range(51)], "NOK", "train", True
    )
    assert sum(r.accepted for r in too_many) == 50 and "max 50" in too_many[-1].reason


# ------------------------------------------------------------------ publication


def make_draft(env):
    d = env.store.create_draft("q", "synthetic-v1")
    did = d["draft_id"]
    env.store.update_items(
        "q",
        did,
        [
            {"file": "train/OK/ok_000.png", "action": "validate", "note": "checked"},
            {"file": "train/NOK/nok_001.png", "action": "relabel", "label": "OK"},
            {"file": "test/NOK/nok_005.png", "action": "exclude"},
        ],
    )
    env.store.import_files("q", did, [("new.png", io.BytesIO(png(150)))], "NOK", "train", True)
    return did


def test_publication_writes_a_verified_immutable_version_manifest_last(env):
    before = snapshot_v1(env.files)
    did = make_draft(env)
    job = env.store.start_publish("q", did, "synthetic-v2", background=False)
    assert job.state == "succeeded", job.error
    folder = [w for w in env.files.writes if "/synthetic-v2/" in w]
    assert folder[-1].endswith("/synthetic-v2/manifest.json")  # manifest written LAST
    raw = env.files.data[f"{ROOT}/synthetic-v2/manifest.json"]
    m = json.loads(raw)
    assert job.manifest_sha256 == sha(raw)
    assert m["parent_version"] == "synthetic-v1" and m["parent_manifest_sha256"] == env.v1_sha
    assert m["changes"] == {"validated": 1, "corrected": 1, "excluded": 1, "imported": 1}
    for item in m["items"]:  # every file present with its recorded SHA-256
        assert sha(env.files.data[f"{ROOT}/synthetic-v2/{item['file']}"]) == item["sha256"]
    corrected = next(i for i in m["items"] if i.get("previous_label"))
    assert corrected["label"] == "OK" and corrected["file"] == "train/OK/nok_001.png"
    assert corrected["label_history"][-1] == {
        "version": "synthetic-v2",
        "label": "OK",
        "review": "corrected",
    }
    assert m["excluded_items"][0]["file"] == "test/NOK/nok_005.png"
    assert m["evaluation_reference_changed"] is True
    assert {i["split"] for i in m["items"] if i["origin"].get("version") == "synthetic-v1"} == {
        "train",
        "validation",
        "test",
    }
    assert snapshot_v1(env.files) == before  # parent untouched
    assert not any("/_locks/" in p for p in env.files.data)  # lock released
    assert env.store.get_draft("q", did)["status"] == "published"
    env.c.w.jobs.run_now.assert_not_called()  # never triggers a training
    idx = env.store.index("q")
    assert [v.version for v in idx.versions] == ["synthetic-v1", "synthetic-v2"]


def test_train_only_changes_keep_the_evaluation_reference(env):
    d = env.store.create_draft("q", "synthetic-v1")
    env.store.update_items(
        "q", d["draft_id"], [{"file": "train/OK/ok_000.png", "action": "validate"}]
    )
    job = env.store.start_publish("q", d["draft_id"], "synthetic-v2", background=False)
    m = json.loads(env.files.data[f"{ROOT}/synthetic-v2/manifest.json"])
    v1 = env.store.version("q", "synthetic-v1")
    assert job.state == "succeeded" and m["evaluation_reference_changed"] is False
    assert m["split_fingerprints"]["test"] == v1.split_fingerprints["test"]
    assert m["split_fingerprints"]["validation"] == v1.split_fingerprints["validation"]


def test_existing_version_is_never_rewritten(env):
    did = make_draft(env)
    env.store.start_publish("q", did, "synthetic-v2", background=False)
    other = env.store.create_draft("q", "synthetic-v1")
    env.store.update_items(
        "q", other["draft_id"], [{"file": "train/OK/ok_000.png", "action": "validate"}]
    )
    with pytest.raises(ConflictError):
        env.store.start_publish("q", other["draft_id"], "synthetic-v2", background=False)
    with pytest.raises(ConflictError):
        env.store.start_publish("q", did, "synthetic-v3", background=False)  # already published
    with pytest.raises(InvalidDatasetRequest):
        env.store.start_publish("q", other["draft_id"], "code", background=False)


def test_interrupted_publication_is_not_a_version_and_can_be_resumed(env):
    did = make_draft(env)
    env.files.fail_on = "/synthetic-v2/train/OK/ok_000.png"
    job = env.store.start_publish("q", did, "synthetic-v2", background=False)
    assert job.state == "failed"
    idx = env.store.index("q")
    assert [v.version for v in idx.versions] == ["synthetic-v1"]
    assert idx.incomplete[0].version == "synthetic-v2" and idx.incomplete[0].state == "interrupted"
    assert idx.incomplete[0].draft_id == did
    other = env.store.create_draft("q", "synthetic-v1")
    env.store.update_items(
        "q", other["draft_id"], [{"file": "train/OK/ok_000.png", "action": "validate"}]
    )
    with pytest.raises(ConflictError):  # nobody else can take the folder
        env.store.start_publish("q", other["draft_id"], "synthetic-v2", background=False)
    with pytest.raises(ConflictError):  # a draft being published cannot be deleted
        env.store.delete_draft("q", did)
    env.files.fail_on = None
    resumed = env.store.start_publish("q", did, "synthetic-v2", background=False)
    assert resumed.state == "succeeded" and resumed.resumed


def test_a_fresh_lock_of_another_process_blocks_publication(env):
    did = make_draft(env)
    env.files.data[f"{ROOT}/_locks/synthetic-v2.lock"] = manifest_bytes(
        {"token": "other", "draft_id": "aaaaaaaaaaaa", "acquired_at": "2999-01-01T00:00:00+00:00"}
    )
    job = env.store.start_publish("q", did, "synthetic-v2", background=False)
    assert job.state == "failed" and "another process" in job.error
    assert f"{ROOT}/_locks/synthetic-v2.lock" in env.files.data  # never removed: not ours


def test_manifest_build_is_deterministic(env):
    did = make_draft(env)
    draft = env.store.get_draft("q", did)
    a, plan_a = build_manifest(
        env.v1, env.v1_sha, draft, "synthetic-v2", "2026-11-26T00:00:00+00:00", "quality"
    )
    b, plan_b = build_manifest(
        env.v1, env.v1_sha, draft, "synthetic-v2", "2026-11-26T00:00:00+00:00", "quality"
    )
    assert manifest_bytes(a) == manifest_bytes(b) and plan_a == plan_b


def test_delete_draft_only_touches_its_folder(env):
    did = make_draft(env)
    before = {p for p in env.files.data if "/_drafts/" not in p}
    env.store.delete_draft("q", did)
    assert not any(f"/_drafts/{did}/" in p for p in env.files.data)
    assert {p for p in env.files.data if "/_drafts/" not in p} == before


def test_training_dataset_is_read_from_the_job_definition(env):
    env.c.w.jobs.list.return_value = [SimpleNamespace(job_id=7)]
    task = SimpleNamespace(
        notebook_task=SimpleNamespace(
            base_parameters={
                "args": json.dumps(["--code-dir", "x", "--dataset-dir", f"{ROOT}/synthetic-v1"])
            }
        )
    )
    env.c.w.jobs.get.return_value = SimpleNamespace(settings=SimpleNamespace(tasks=[task]))
    td = env.store.training_dataset("q")
    assert td.dataset_version == "synthetic-v1" and td.source.startswith("job definition")


# ------------------------------------------------------------------ API


@pytest.fixture
def api(env):
    app = FastAPI()
    app.include_router(routes.create_mlops_router(lambda: env.c), prefix="/api")
    return TestClient(app)


def test_api_end_to_end(api, env):
    idx = api.get("/api/mlops/models/q/datasets")
    assert idx.status_code == 200 and idx.headers["x-hovis-cache"] == "miss"
    img = api.get("/api/mlops/models/q/datasets/synthetic-v1/images/train/OK/ok_000.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert "immutable" in img.headers["cache-control"]
    assert api.get("/api/mlops/models/q/datasets/synthetic-v1/images/code/x.py").status_code == 400
    draft = api.post(
        "/api/mlops/models/q/dataset-drafts", json={"parent_version": "synthetic-v1"}
    ).json()
    base = f"/api/mlops/models/q/dataset-drafts/{draft['draft_id']}"
    patch = api.patch(
        f"{base}/items", json={"changes": [{"file": "train/OK/ok_000.png", "action": "validate"}]}
    )
    assert patch.status_code == 200
    imported = api.post(
        f"{base}/import",
        files=[("files", ("a.png", png(170), "image/png"))],
        data={"label": "OK", "split": "train", "synthetic_attested": "true"},
    )
    assert imported.status_code == 200 and imported.json()[0]["accepted"]
    assert api.get(f"{base}/images/{imported.json()[0]['sha256']}").status_code == 200
    job = api.post(f"{base}/publish", json={"version": "synthetic-v2"})
    assert job.status_code == 202
    for _ in range(200):
        state = api.get(f"/api/mlops/dataset-jobs/{job.json()['job_id']}").json()
        if state["state"] != "running":
            break
        import time

        time.sleep(0.02)
    assert state["state"] == "succeeded" and state["done"] == state["total"]
    versions = api.get("/api/mlops/models/q/datasets").json()["versions"]
    assert [v["version"] for v in versions] == ["synthetic-v1", "synthetic-v2"]  # cache invalidated


# ------------------------------------------------------------------ Delta option B


class FakeWriter:
    def __init__(self, sink, table_rows):
        self.sink, self.options, self.rows = sink, {}, table_rows

    def mode(self, m):
        self.mode_ = m
        return self

    def option(self, k, v):
        self.options[k] = v
        return self

    def saveAsTable(self, table):  # noqa: N802 - Spark API name
        existing = self.sink.setdefault(table, [])
        where = self.options.get("replaceWhere")
        if where:
            version = where.split("'")[1]
            existing[:] = [r for r in existing if r["dataset_version"] != version]
        else:
            existing.clear()
        existing.extend(self.rows)


class FakeSpark:
    def __init__(self):
        self.tables: dict[str, list] = {}
        self.catalog = SimpleNamespace(tableExists=lambda t: t in self.tables)

    def createDataFrame(self, rows):  # noqa: N802 - Spark API name
        return SimpleNamespace(write=FakeWriter(self.tables, rows))


def test_delta_writes_keep_other_versions_and_are_idempotent():
    from mlops.databricks_poc.remote.train_quality import delta_write_options, write_version_rows

    spark, table = FakeSpark(), "s.annotations"
    v1 = [{"file": f"a{i}", "dataset_version": "synthetic-v1"} for i in range(3)]
    v2 = [{"file": f"b{i}", "dataset_version": "synthetic-v2"} for i in range(2)]
    write_version_rows(spark, v1, table, "synthetic-v1")  # creates the table
    write_version_rows(spark, v2, table, "synthetic-v2")
    write_version_rows(spark, v2, table, "synthetic-v2")  # same version again: no duplicate
    rows = spark.tables[table]
    assert sorted(r["dataset_version"] for r in rows) == ["synthetic-v1"] * 3 + ["synthetic-v2"] * 2
    assert delta_write_options(True, "synthetic-v2") == {
        "replaceWhere": "dataset_version = 'synthetic-v2'"
    }
    with pytest.raises(ValueError):
        delta_write_options(True, "x' OR '1'='1")


def test_parallel_index_keeps_the_request_context(env):
    """The index reads run in threads: `fresh` must still reach them (real re-read)."""
    from mlops.databricks.read_cache import read_scope

    env.store.index("q")
    calls = env.c.mlflow.get_registered_model.call_count
    env.store.index("q")  # cached
    assert env.c.mlflow.get_registered_model.call_count == calls
    with read_scope(fresh=True) as scope:
        env.store.index("q")
    assert env.c.mlflow.get_registered_model.call_count == calls + 1
    assert scope.headers()["X-HOVIS-Cache"] in ("miss", "mixed")
