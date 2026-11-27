"""Local-only package construction, provenance and immutable retrieval."""

import pytest

from mlops.edge_packages import PackageBuilder, PackageError, PackageStore
from mlops.edge_packages.sources import (
    DatabricksMetadataSource,
    LocalFixtureSource,
    VersionEvidence,
)
from mlops.tests.test_delivery import POLICY, delivery
from visionhub.integration.mlops import ModelPackage


class FixtureMetadata:
    def __init__(self, package: ModelPackage):
        self.package = package
        self.approval = "approved"
        self.hash = package.dataset.manifest_sha256

    def resolve(self, registered_model, version):
        return VersionEvidence(
            registered_model,
            version,
            self.package.model.mlflow_run_id,
            self.approval,
            "local-test",
            False,
            {"argos.manifest_sha256": self.hash},
        )

    def artifact_inventory(self, evidence):
        return [self.package.artifact.uri]


def setup(tmp_path):
    folder = delivery(tmp_path)
    package = ModelPackage.model_validate_json((folder / "model-package.json").read_text())
    source = FixtureMetadata(package)
    store = PackageStore(tmp_path / "off-git-packages", POLICY)
    builder = PackageBuilder(source, LocalFixtureSource(folder), store)
    return folder, package, source, store, builder


def test_local_package_is_immutable_and_not_deployable(tmp_path):
    folder, package, _, store, builder = setup(tmp_path)
    inspection = builder.inspect(package.model.registered_model, package.model.version)
    assert not inspection.eligible
    assert "local test evidence" in inspection.blockers[0]
    first = builder.build(package)
    second = builder.build(package)
    assert first == second
    assert not first.deployable
    assert store.find(package.model.registered_model, package.model.version) == [first]
    with pytest.raises(PermissionError, match="test-only"):
        store.get(first.digest)
    assert store.get(first.digest, require_deployable=False) == first
    (folder / "model.onnx").write_bytes(b"modified")
    assert (first.folder / "model.onnx").read_bytes() == b"weights"


def test_reject_unapproved_run_and_dataset_mismatch(tmp_path):
    _, package, source, _, builder = setup(tmp_path)
    source.approval = "candidate"
    with pytest.raises(PackageError, match="not currently approved"):
        builder.build(package)
    source.approval = "approved"
    source.hash = "0" * 64
    with pytest.raises(PackageError, match="dataset manifest hash"):
        builder.build(package)
    source.hash = package.dataset.manifest_sha256
    wrong = package.model_copy(deep=True)
    wrong.model.mlflow_run_id = "different-run"
    with pytest.raises(PackageError, match="ModelRef run"):
        builder.build(wrong)


def test_reject_corrupt_source_and_stored_package(tmp_path):
    folder, package, _, store, builder = setup(tmp_path)
    (folder / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(PackageError, match="size mismatch"):
        builder.build(package)
    (folder / "model.onnx").write_bytes(b"weights")
    record = builder.build(package)
    (record.folder / "model.onnx").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="invalid package"):
        store.get(record.digest, require_deployable=False)


def test_store_rejects_unsafe_output_and_provenance_tampering(tmp_path):
    folder, package, _, store, builder = setup(tmp_path)
    unsafe = package.model_copy(deep=True)
    unsafe.artifact.uri = "../escaped.onnx"
    with pytest.raises(ValueError, match="unsafe package artifact path"):
        store.publish(
            unsafe, folder / "model.onnx", trust_level="test_only", source_id="local-test"
        )
    assert not (store.root / "escaped.onnx").exists()
    record = builder.build(package)
    (record.folder / "provenance.json").write_text(
        '{"source_id":"local-test","trust_level":"verified"}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        store.get(record.digest)


def test_local_source_rejects_traversal(tmp_path):
    folder, _, _, _, _ = setup(tmp_path)
    source = LocalFixtureSource(folder)
    for name in ("../outside.pt", "C:/outside.pt", "foo\\bar.pt"):
        with pytest.raises(ValueError, match="invalid artifact path"):
            source.path(name)


def test_store_must_be_outside_checkout():
    from pathlib import Path

    checkout = Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="outside"):
        PackageStore(checkout / "mlops" / "bad-store", POLICY)


def test_databricks_metadata_reads_version_and_run_fresh():
    from types import SimpleNamespace as NS

    class Client:
        def get_model_version(self, name, version):
            assert (name, version) == ("catalog.schema.quality", "3")
            return NS(
                name=name,
                version=version,
                run_id="run-3",
                source="run:/run-3/model",
                tags={"argos_approval": "approved"},
            )

        def get_run(self, run_id):
            return NS(info=NS(run_id=run_id), data=NS(tags={"argos.manifest_sha256": "a" * 64}))

        def list_artifacts(self, run_id, path):
            assert run_id == "run-3"
            return [NS(path="model/weights.onnx", is_dir=False)] if not path else []

    class Connector:
        mlflow = Client()

        @staticmethod
        def _call(fn, _what):
            return fn()

    source = DatabricksMetadataSource(Connector())
    evidence = source.resolve("catalog.schema.quality", "3")
    assert evidence.authoritative and evidence.approval == "approved"
    assert source.artifact_inventory(evidence) == ["run/model/weights.onnx"]


def test_logged_model_inventory_recurses_without_duplicate_folder(monkeypatch):
    import sys
    from types import SimpleNamespace as NS

    class Client:
        @staticmethod
        def list_artifacts(_run_id, _path):
            return []

        @staticmethod
        def get_logged_model(_model_id):
            return NS(
                model_id="m-3", source_run_id="run-3", artifact_location="dbfs:/model/artifacts"
            )

    class Connector:
        mlflow = Client()

        @staticmethod
        def _call(fn, _what):
            return fn()

    def list_artifacts(*, artifact_uri):
        if artifact_uri == "dbfs:/model/artifacts":
            return [NS(path="artifacts/artifacts", is_dir=True)]
        if artifact_uri == "dbfs:/model/artifacts/artifacts":
            return [NS(path="artifacts/classifier.joblib", is_dir=False)]
        raise AssertionError(artifact_uri)

    monkeypatch.setitem(sys.modules, "mlflow", NS(artifacts=NS(list_artifacts=list_artifacts)))
    evidence = VersionEvidence("catalog.schema.quality", "3", "run-3", "approved", "models:/m-3")
    assert DatabricksMetadataSource(Connector()).artifact_inventory(evidence) == [
        "logged_model/artifacts/classifier.joblib"
    ]
