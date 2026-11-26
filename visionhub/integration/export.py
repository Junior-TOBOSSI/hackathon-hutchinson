"""Export the integration artifacts consumed by the other workstreams.

    python -m visionhub.integration.export           # (re)write the files
    python -m visionhub.integration.export --check   # fail if a file is out of date (CI)

Outputs:
- frontend/openapi/edge.openapi.json       OpenAPI of the Edge API (historical + /production)
- frontend/openapi/contracts.openapi.json  JSON Schemas of the integration contracts
- frontend/src/mocks/fixtures/**.json      validated synthetic fixtures (mock mode)
- mlops/examples/model-package.example.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema

from visionhub import __version__
from visionhub.config import Settings
from visionhub.contracts import UseCase
from visionhub.integration import core_api, edge_events, mlops, vision
from visionhub.integration.fixtures import build_fixtures, package

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"

CONTRACT_MODELS = [
    edge_events.EdgeEvent,
    edge_events.EdgeEventBatch,
    edge_events.IngestAck,
    core_api.StationSummary,
    core_api.Alert,
    core_api.OperatorReport,
    mlops.DatasetRef,
    mlops.TrainingConfig,
    mlops.TrainingJob,
    mlops.EvaluationMetrics,
    mlops.ModelRef,
    mlops.ModelPackage,
    mlops.ModelDeployment,
    mlops.StationDeploymentStatus,
    mlops.MonitoringMetrics,
    mlops.RetrainingPolicy,
    vision.DangerZone,
    vision.PPEReport,
    vision.BehaviorReport,
]


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def edge_openapi() -> dict:
    from visionhub.argos_app import create_argos_app

    settings = Settings(_env_file=None, db_path=":memory:", pipeline_enabled=False)
    return create_argos_app(settings).openapi()


def contracts_openapi() -> dict:
    _, schema = models_json_schema(
        [(m, "serialization") for m in CONTRACT_MODELS],
        ref_template="#/components/schemas/{model}",
    )
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ARGOS integration contracts (schemas only)",
            "version": __version__,
            "description": "Edge->Core events, Core read models, MLOps contracts. "
            "No paths: Core endpoints are specified in docs/integration-contracts.md.",
        },
        "paths": {},
        "components": {"schemas": schema["$defs"]},
    }


def artifacts() -> dict[Path, str]:
    files = {
        FRONTEND / "openapi" / "edge.openapi.json": dumps(edge_openapi()),
        FRONTEND / "openapi" / "contracts.openapi.json": dumps(contracts_openapi()),
        ROOT / "mlops" / "examples" / "model-package.example.json": dumps(
            package(UseCase.QUALITY).model_dump(mode="json")
        ),
    }
    for name, (kind, value) in build_fixtures().items():
        adapter = TypeAdapter(kind)
        data = adapter.dump_python(adapter.validate_python(value), mode="json")
        files[FRONTEND / "src" / "mocks" / "fixtures" / f"{name}.json"] = dumps(data)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check, write nothing")
    args = parser.parse_args(argv)
    stale = []
    for path, content in artifacts().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        stale.append(path.relative_to(ROOT).as_posix())
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if args.check and stale:
        print("Out of date (run python -m visionhub.integration.export):", *stale, sep="\n  ")
        return 1
    print(f"{len(stale)} file(s) {'to update' if args.check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
