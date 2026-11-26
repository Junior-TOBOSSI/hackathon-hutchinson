"""Check a model delivery folder against the ARGOS delivery contract.

    python -m mlops.delivery.validate_delivery <folder> [--import-analyzer]

See mlops/docs/model-delivery-contract.md. Exit code 0 = deliverable can be integrated.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from visionhub.analyzer import Analyzer
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


def validate(folder: Path, import_analyzer: bool = False) -> list[str]:
    """Return the list of problems (empty = OK)."""
    problems = [f"missing file: {name}" for name in REQUIRED_FILES if not (folder / name).is_file()]
    package = None
    if (folder / "model-package.json").is_file():
        try:
            package = ModelPackage.model_validate_json(
                (folder / "model-package.json").read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            problems.append(
                f"model-package.json does not match ModelPackage: {exc.error_count()} error(s): "
                f"{exc.errors()[0]['msg']}"
            )
    if (folder / "requirements.txt").is_file():
        for line in (folder / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not PINNED.match(line):
                problems.append(f"requirements.txt: not pinned with '==': {line}")
    if package is not None:
        module_file = package.analyzer_class.split(":")[0].split(".")[-1] + ".py"
        if not (folder / module_file).is_file():
            problems.append(f"analyzer module {module_file} not found in the delivery")
        artifact = folder / package.artifact.uri
        if artifact.is_file():
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if digest != package.artifact.sha256:
                problems.append(f"artifact sha256 mismatch for {package.artifact.uri}")
        if import_analyzer:
            module, _, name = package.analyzer_class.partition(":")
            sys.path.insert(0, str(folder))
            try:
                cls = getattr(importlib.import_module(module.split(".")[-1]), name)
                if (
                    not (isinstance(cls, type) and issubclass(cls, Analyzer))
                    or cls.use_case != package.use_case
                ):
                    problems.append(
                        f"{package.analyzer_class} is not an Analyzer for {package.use_case.value}"
                    )
            except Exception as exc:  # noqa: BLE001 - report any import problem
                problems.append(
                    f"cannot import {package.analyzer_class}: {type(exc).__name__}: {exc}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument(
        "--import-analyzer", action="store_true", help="also import the Analyzer class"
    )
    args = parser.parse_args(argv)
    problems = validate(args.folder, args.import_analyzer)
    print(
        json.dumps({"folder": str(args.folder), "ok": not problems, "problems": problems}, indent=2)
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
