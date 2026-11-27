"""The validator must reject incomplete or unsafe Edge deliveries."""

import hashlib
import json
from pathlib import Path

import pytest

from mlops.delivery.validate_delivery import AllowedAdapter, validate

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "model-package.example.json"
POLICY = {
    "usecases.quality.analyzer:OnnxAnalyzer": AllowedAdapter(
        "onnxruntime", frozenset({"onnx"}), frozenset({"cpu"}), frozenset({"postprocessing"})
    )
}


def delivery(tmp_path: Path) -> Path:
    folder = tmp_path / "delivery"
    folder.mkdir()
    artifact = b"weights"
    package = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    package["artifact"].update(
        sha256=hashlib.sha256(artifact).hexdigest(), size_bytes=len(artifact)
    )
    package["params"]["postprocessing"] = {
        "score_direction": "higher_is_worse",
        "positive_class": "NOK",
    }
    (folder / "model-package.json").write_text(json.dumps(package), encoding="utf-8")
    for name in ("README.md", "train.py", "evaluate.py", "config.yaml"):
        (folder / name).write_text("# placeholder\n", encoding="utf-8")
    (folder / "requirements.txt").write_text("onnxruntime==1.20.0\n", encoding="utf-8")
    (folder / "model.onnx").write_bytes(artifact)
    return folder


def edit(folder: Path, callback) -> None:
    path = folder / "model-package.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    callback(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_valid_delivery(tmp_path):
    assert validate(delivery(tmp_path), POLICY) == []


def test_missing_wrong_size_and_hash(tmp_path):
    folder = delivery(tmp_path)
    (folder / "model.onnx").write_bytes(b"tampered")
    problems = validate(folder, POLICY)
    assert any("size mismatch" in p for p in problems)
    assert any("sha256 mismatch" in p for p in problems)
    (folder / "model.onnx").unlink()
    assert any("artifact missing" in p for p in validate(folder, POLICY))


def test_path_and_symlink_rejected(tmp_path):
    folder = delivery(tmp_path)
    for uri in ("../outside.onnx", str(tmp_path / "outside.onnx")):
        edit(folder, lambda p, value=uri: p["artifact"].update(uri=value))
        assert any("relative file" in p for p in validate(folder, POLICY))
    edit(folder, lambda p: p["artifact"].update(uri="linked.onnx"))
    outside = tmp_path / "outside.onnx"
    outside.write_bytes(b"weights")
    try:
        (folder / "linked.onnx").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise
    assert any("symlink" in p for p in validate(folder, POLICY))


def test_runtime_adapter_and_configuration_rejected(tmp_path):
    folder = delivery(tmp_path)
    edit(folder, lambda p: p.update(runtime="torch"))
    assert any("incompatible" in p for p in validate(folder, POLICY))
    edit(folder, lambda p: p.update(runtime="onnxruntime", analyzer_class="unknown:Adapter"))
    assert any("not authorized" in p for p in validate(folder, POLICY))
    edit(
        folder,
        lambda p: p.update(analyzer_class="usecases.quality.analyzer:OnnxAnalyzer", params={}),
    )
    assert any("incomplete" in p or "postprocessing" in p for p in validate(folder, POLICY))


def test_classes_thresholds_and_delivery_files(tmp_path):
    folder = delivery(tmp_path)
    edit(folder, lambda p: p.update(classes=["OK", "OK"]))
    assert any("classes" in p for p in validate(folder, POLICY))
    edit(folder, lambda p: p.update(thresholds={"low": 0.9, "high": 0.1}))
    assert any("does not match ModelPackage" in p for p in validate(folder, POLICY))
    (folder / "evaluate.py").unlink()
    (folder / "requirements.txt").write_text("onnxruntime>=1.0\n", encoding="utf-8")
    problems = validate(folder, POLICY)
    assert any("evaluate.py" in p for p in problems)
    assert any("not pinned" in p for p in problems)
