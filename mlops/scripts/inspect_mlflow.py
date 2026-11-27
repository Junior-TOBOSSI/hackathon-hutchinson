"""Explore MLflow THROUGH the ARGOS connector (what a FastAPI service would do).

    python -m mlops.scripts.inspect_mlflow ping
    python -m mlops.scripts.inspect_mlflow experiments
    python -m mlops.scripts.inspect_mlflow runs argos-foundation-demo
    python -m mlops.scripts.inspect_mlflow params <run_id>
    python -m mlops.scripts.inspect_mlflow metrics <run_id>
    python -m mlops.scripts.inspect_mlflow history <run_id> history_val_accuracy
    python -m mlops.scripts.inspect_mlflow artifacts <run_id> [path]
    python -m mlops.scripts.inspect_mlflow download <run_id> reports/confusion_matrix.png
    python -m mlops.scripts.inspect_mlflow models
    python -m mlops.scripts.inspect_mlflow versions argos-foundation-demo-model
    python -m mlops.scripts.inspect_mlflow resolve models:/argos-foundation-demo-model@champion
    python -m mlops.scripts.inspect_mlflow set-alias argos-foundation-demo-model champion 2

Every answer is printed as JSON: exactly what an API would return to the AI Leader UI.
"""

from __future__ import annotations

import argparse
import json
import sys

from pydantic import BaseModel

from mlops.config import utf8_console
from mlops.connectors import ArgosMlflowConnector, MlflowConnectorError


def show(value) -> None:
    def plain(item):
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, list):
            return [plain(i) for i in item]
        if isinstance(item, dict):
            return {k: plain(v) for k, v in item.items()}
        return str(item) if not isinstance(item, (int, float, str, bool, type(None))) else item

    print(json.dumps(plain(value), indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="ARGOS MLflow connector explorer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping")
    sub.add_parser("experiments")
    sub.add_parser("runs").add_argument("experiment", help="experiment id or name")
    for name in ("params", "metrics"):
        sub.add_parser(name).add_argument("run_id")
    history = sub.add_parser("history")
    history.add_argument("run_id")
    history.add_argument("key")
    artifacts = sub.add_parser("artifacts")
    artifacts.add_argument("run_id")
    artifacts.add_argument("path", nargs="?")
    download = sub.add_parser("download")
    download.add_argument("run_id")
    download.add_argument("path")
    sub.add_parser("models")
    sub.add_parser("versions").add_argument("model")
    sub.add_parser("resolve").add_argument(
        "model_uri", help="models:/<name>/<v> or models:/<name>@<alias>"
    )
    alias = sub.add_parser("set-alias")
    alias.add_argument("model")
    alias.add_argument("alias")
    alias.add_argument("version")
    args = parser.parse_args(argv)

    connector = ArgosMlflowConnector()
    try:
        match args.command:
            case "ping":
                show(connector.ping())
            case "experiments":
                show(connector.list_experiments())
            case "runs":
                runs = connector.list_runs(args.experiment)
                show(
                    [
                        {k: v for k, v in r.model_dump(mode="json").items() if k != "params"}
                        for r in runs
                    ]
                )
            case "params":
                show(connector.get_run_params(args.run_id))
            case "metrics":
                show(connector.get_run_metrics(args.run_id))
            case "history":
                show(connector.get_metric_history(args.run_id, args.key))
            case "artifacts":
                show(connector.list_artifacts(args.run_id, args.path))
            case "download":
                path = connector.download_artifact(args.run_id, args.path)
                print(f"Downloaded to {path}")
            case "models":
                show(connector.list_registered_models())
            case "versions":
                show(connector.list_model_versions(args.model))
            case "resolve":
                version = connector.resolve(args.model_uri)
                alias = args.model_uri.split("@", 1)[1] if "@" in args.model_uri else None
                show(
                    {"version": version, "argos_model_ref": connector.to_model_ref(version, alias)}
                )
            case "set-alias":
                show(connector.set_demo_alias(args.model, args.alias, args.version))
    except MlflowConnectorError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
