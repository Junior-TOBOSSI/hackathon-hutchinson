"""SCI-02 explicit industrial publication: local checks, dry run by default, triple guard,
catalogue guarantees (no overwrite, verify, manifest last, lock removed). Fake Volume only."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from mlops.datasets_prep import publish_industrial as pub


def prepared(tmp_path, synthetic=False, leak=False):
    items = []
    for i, (split, d) in enumerate(
        [("train", "train"), ("validation", "val"), ("test", "test")] * 2
    ):
        data = f"image-{i}".encode()
        f = tmp_path / d / "OK" / f"img{i}.jpg"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        group = "R1" if leak else f"R{i}"
        items.append(
            {
                "file": f"{d}/OK/img{i}.jpg",
                "label": "OK",
                "split": split,
                "group": group,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    m = {
        "schema_version": 2,
        "dataset_id": "quality-industrial-binary",
        "dataset_version": "binary-pli0",
        "use_case": "quality",
        "classes": ["OK", "NOK"],
        "synthetic": synthetic,
        "counts": {"train": {"OK": 2}, "validation": {"OK": 2}, "test": {"OK": 2}},
        "items": items,
    }
    (tmp_path / pub.DRAFT).write_text(json.dumps(m), encoding="utf-8")
    return tmp_path


class Volume:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.order: list[str] = []
        self.catalog_root = "/Volumes/x/_families"
        self.families: list[str] = []
        self.deleted: list[str] = []
        self.c = SimpleNamespace(_call=lambda fn, what: fn())
        self.w = SimpleNamespace(files=SimpleNamespace(delete=lambda p: self.deleted.append(p)))

    def _exists(self, p):
        return p in self.files

    def _upload(self, p, data, overwrite=False):
        assert overwrite or p not in self.files, f"overwrite of {p}"
        self.files[p] = data
        self.order.append(p)

    def _download(self, p):
        return self.files[p]

    def _verify(self, p, sha):
        assert hashlib.sha256(self.files[p]).hexdigest() == sha

    def _acquire_lock(self, p, token, owner):
        self._upload(p, b"lock")

    def create_family(self, ds, name, use_case, classes, synthetic, description=None):
        self.families.append(ds)

    def _refresh_family_summary(self, scope):
        self.refreshed = scope


@pytest.fixture
def vol(monkeypatch):
    v = Volume()
    import mlops.api.routes as routes
    import mlops.databricks.datasets as datasets

    monkeypatch.setattr(routes, "default_connector", lambda: None)
    monkeypatch.setattr(datasets, "dataset_store", lambda c: v)
    monkeypatch.delenv("HOVIS_INDUSTRIAL_TRANSFER", raising=False)
    return v


def test_local_checks_refuse_synthetic_flags_and_burst_leaks(tmp_path):
    assert pub.check_local(prepared(tmp_path / "a"))[1] == []
    assert any(
        "synthetic=false" in e for e in pub.check_local(prepared(tmp_path / "b", synthetic=True))[1]
    )
    assert any("burst" in e for e in pub.check_local(prepared(tmp_path / "c", leak=True))[1])
    d = prepared(tmp_path / "d")
    (d / "train" / "OK" / "img0.jpg").write_bytes(b"changed")
    assert any("SHA-256 mismatch" in e for e in pub.check_local(d)[1])


def test_dry_run_by_default_and_execute_needs_the_triple_guard(tmp_path, vol, monkeypatch):
    d = prepared(tmp_path)
    assert pub.main(["--prepared", str(d)]) == 0 and vol.files == {}
    assert pub.main(["--prepared", str(d), "--execute"]) == 3 and vol.files == {}
    monkeypatch.setenv("HOVIS_INDUSTRIAL_TRANSFER", "1")
    assert (
        pub.main(["--prepared", str(d), "--execute", "--confirm", "other/v"]) == 3
        and vol.files == {}
    )


def test_execute_publishes_with_catalogue_guarantees(tmp_path, vol, monkeypatch):
    d = prepared(tmp_path)
    monkeypatch.setenv("HOVIS_INDUSTRIAL_TRANSFER", "1")
    assert (
        pub.main(
            [
                "--prepared",
                str(d),
                "--execute",
                "--confirm",
                "quality-industrial-binary/binary-pli0",
            ]
        )
        == 0
    )
    root = "/Volumes/x/_families/quality-industrial-binary"
    assert vol.families == ["quality-industrial-binary"]
    assert vol.order[-1] == f"{root}/binary-pli0/manifest.json"  # manifest written LAST
    assert len([p for p in vol.files if p.endswith(".jpg")]) == 6
    assert vol.deleted == [f"{root}/_locks/binary-pli0.lock"]  # lock always removed
    manifest = json.loads(vol.files[f"{root}/binary-pli0/manifest.json"])
    assert (
        manifest["synthetic"] is False
        and manifest["provenance"]["publication"] == "industrial explicit path"
    )
    # a published version is immutable: a second run does nothing
    assert (
        pub.main(
            [
                "--prepared",
                str(d),
                "--execute",
                "--confirm",
                "quality-industrial-binary/binary-pli0",
            ]
        )
        == 0
    )
