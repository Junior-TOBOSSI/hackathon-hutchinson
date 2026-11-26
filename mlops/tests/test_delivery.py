import hashlib
import shutil
from pathlib import Path

from mlops.delivery.validate_delivery import validate

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "model-package.example.json"

ANALYZER = """
from visionhub.analyzer import Analyzer
from visionhub.contracts import AnalysisResult, QualityDetails, UseCase


class OnnxAnalyzer(Analyzer):
    use_case = UseCase.QUALITY
    name = "argos-quality"
    version = "3"

    def load(self, config):
        pass

    def analyze(self, image, meta):
        return AnalysisResult(use_case=self.use_case, score=0.1, model_name=self.name,
                              model_version=self.version, details=QualityDetails())
"""


def delivery(tmp_path: Path, artifact: bytes = b"weights") -> Path:
    folder = tmp_path / "delivery"
    folder.mkdir()
    package = EXAMPLE.read_text(encoding="utf-8").replace(
        '"abdf7a0c7cf1edb79434722f2d1df660695231efee9e9329ffa4c79b3dc6370b"',
        f'"{hashlib.sha256(b"weights").hexdigest()}"',
    )
    (folder / "model-package.json").write_text(package, encoding="utf-8")
    for name in ("README.md", "train.py", "evaluate.py", "config.yaml"):
        (folder / name).write_text("# placeholder\n", encoding="utf-8")
    (folder / "requirements.txt").write_text(
        "onnxruntime==1.20.0\nnumpy==2.4.6\n", encoding="utf-8"
    )
    (folder / "analyzer.py").write_text(ANALYZER, encoding="utf-8")
    (folder / "model.onnx").write_bytes(artifact)
    return folder


def test_valid_delivery(tmp_path):
    assert validate(delivery(tmp_path), import_analyzer=True) == []


def test_problems_are_reported(tmp_path):
    folder = delivery(tmp_path, artifact=b"tampered")
    (folder / "evaluate.py").unlink()
    (folder / "requirements.txt").write_text("onnxruntime>=1.0\n", encoding="utf-8")
    problems = validate(folder)
    assert any("evaluate.py" in p for p in problems)
    assert any("not pinned" in p for p in problems)
    assert any("sha256 mismatch" in p for p in problems)


def test_invalid_manifest(tmp_path):
    folder = delivery(tmp_path)
    (folder / "model-package.json").write_text('{"package_schema": "wrong"}', encoding="utf-8")
    assert any("does not match ModelPackage" in p for p in validate(folder))
    shutil.rmtree(folder)
