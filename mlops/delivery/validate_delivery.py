"""Validate a model delivery or a runtime package without importing its code.

An explicit adapter allowlist is required. Integrity checks do not establish that an
artifact came from a trusted producer; the package builder verifies provenance separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from pydantic import ValidationError

from visionhub.integration.mlops import ModelPackage

REQUIRED_FILES = (
    "model-package.json",
    "README.md",
    "requirements.txt",
    "train.py",
    "evaluate.py",
    "config.yaml",
)
PINNED = re.compile(r"^[A-Za-z0-9_.\-\[\]]+==[^=\s]+$")
RUNTIME_FORMATS = {
    "onnxruntime": frozenset({"onnx"}),
    "ultralytics": frozenset({"pt"}),
    "torch": frozenset({"pt", "torchscript"}),
    "opencv": frozenset({"onnx"}),
}


@dataclass(frozen=True)
class AllowedAdapter:
    runtime: str
    formats: frozenset[str]
    devices: frozenset[str]
    required_params: frozenset[str] = frozenset()


def _artifact_path(folder: Path, uri: str) -> tuple[Path | None, str | None]:
    """Resolve one relative artifact path without traversing symlinks or directories."""
    path = Path(uri)
    windows = PureWindowsPath(uri)
    if (
        not uri
        or path.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ":" in uri
        or "\\" in uri
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        return None, "artifact path must be a relative file inside the package"
    current = folder.resolve()
    for part in path.parts:
        current /= part
        if current.is_symlink():
            return None, "artifact path contains a symlink"
    try:
        resolved = current.resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"artifact missing: {uri}"
    if not resolved.is_relative_to(folder.resolve()) or not resolved.is_file():
        return None, "artifact is not a regular file inside the package"
    return resolved, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_package(
    folder: Path, allowed_adapters: dict[str, AllowedAdapter] | None = None
) -> list[str]:
    """Validate the minimal runnable package: manifest, artifact and adapter policy."""
    manifest = folder / "model-package.json"
    if not manifest.is_file() or manifest.is_symlink():
        return ["missing regular file: model-package.json"]
    try:
        package = ModelPackage.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        return [f"model-package.json does not match ModelPackage: {exc}"]

    problems: list[str] = []
    rule = (allowed_adapters or {}).get(package.analyzer_class)
    if rule is None:
        problems.append(f"analyzer adapter is not authorized: {package.analyzer_class}")
    elif (
        rule.runtime != package.runtime
        or package.artifact.format not in rule.formats
        or package.device not in rule.devices
    ):
        problems.append("adapter is incompatible with runtime, format or device")
    elif not rule.required_params.issubset(package.params):
        problems.append("adapter configuration is incomplete")
    if package.artifact.format not in RUNTIME_FORMATS[package.runtime]:
        problems.append("artifact format is incompatible with runtime")
    if (
        not package.classes
        or len(set(package.classes)) != len(package.classes)
        or any(not label.strip() for label in package.classes)
    ):
        problems.append("classes must be nonempty and unique")
    if package.use_case.value == "quality" and not {"OK", "NOK"}.issubset(package.classes):
        problems.append("quality classes must include OK and NOK")
    if package.dataset.classes and set(package.dataset.classes) != set(package.classes):
        problems.append("package classes differ from dataset classes")
    if package.evaluation and package.evaluation.dataset != package.dataset:
        problems.append("evaluation dataset differs from package dataset")
    if (
        package.evaluation
        and package.evaluation.class_order
        and (set(package.evaluation.class_order) != set(package.classes))
    ):
        problems.append("evaluation classes differ from package classes")
    if any(size <= 0 for size in package.preprocessing.input_size):
        problems.append("preprocessing input_size must be positive")
    if package.preprocessing.normalize_std is not None and any(
        value <= 0 for value in package.preprocessing.normalize_std
    ):
        problems.append("preprocessing normalize_std must be positive")
    if package.preprocessing.roi is not None and any(
        size <= 0 for size in package.preprocessing.roi[2:]
    ):
        problems.append("preprocessing ROI width and height must be positive")
    post = package.params.get("postprocessing")
    if not isinstance(post, dict) or post.get("score_direction") != "higher_is_worse":
        problems.append("explicit postprocessing with score_direction=higher_is_worse is required")
    if package.use_case.value == "quality" and (
        not isinstance(post, dict) or post.get("positive_class") != "NOK"
    ):
        problems.append("quality postprocessing must identify NOK as the positive class")
    if package.artifact.size_bytes <= 0:
        problems.append("artifact size must be positive")
    artifact, error = _artifact_path(folder, package.artifact.uri)
    if error:
        problems.append(error)
    elif artifact is not None:
        if artifact.stat().st_size != package.artifact.size_bytes:
            problems.append("artifact size mismatch")
        if _sha256(artifact) != package.artifact.sha256:
            problems.append("artifact sha256 mismatch")
    return problems


def validate(folder: Path, allowed_adapters: dict[str, AllowedAdapter] | None = None) -> list[str]:
    """Validate a full training delivery, including the runnable package."""
    problems = [f"missing file: {name}" for name in REQUIRED_FILES if not (folder / name).is_file()]
    if (folder / "requirements.txt").is_file():
        for line in (folder / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not PINNED.match(line):
                problems.append(f"requirements.txt: not pinned with '==': {line}")
    problems.extend(validate_package(folder, allowed_adapters))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--policy", type=Path, required=True, help="JSON of preinstalled adapters")
    args = parser.parse_args(argv)
    raw = json.loads(args.policy.read_text(encoding="utf-8"))
    policy = {
        name: AllowedAdapter(
            value["runtime"],
            frozenset(value["formats"]),
            frozenset(value["devices"]),
            frozenset(value.get("required_params", [])),
        )
        for name, value in raw.items()
    }
    problems = validate(args.folder, policy)
    print(
        json.dumps({"folder": str(args.folder), "ok": not problems, "problems": problems}, indent=2)
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
