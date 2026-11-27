"""PEDAGOGICAL, READ-ONLY look inside MLflow's SQLite backend store.

    python -m mlops.scripts.inspect_sqlite

The database is opened with ``mode=ro``: nothing can be written. ARGOS code must NEVER do
this in production: the schema is internal to MLflow and changes between versions. The
connector only uses the REST API. This script exists to SEE where metadata lives.
"""

from __future__ import annotations

import sqlite3
import sys

from mlops.config import MlflowSettings, utf8_console

TABLES = [
    "experiments",
    "runs",
    "params",
    "metrics",
    "latest_metrics",
    "tags",
    "datasets",
    "inputs",
    "logged_models",
    "registered_models",
    "model_versions",
    "registered_model_aliases",
]

QUERIES = {
    "Runs of the demo experiment": """
        SELECT r.run_uuid, r.name, r.status, r.lifecycle_stage, r.artifact_uri
        FROM runs r JOIN experiments e ON e.experiment_id = r.experiment_id
        WHERE e.name = 'argos-foundation-demo' AND r.lifecycle_stage = 'active'""",
    "Model versions and their origin": """
        SELECT name, version, run_id, source, status FROM model_versions ORDER BY name, version""",
    "Aliases": "SELECT name, alias, version FROM registered_model_aliases",
}


def main() -> int:
    utf8_console()
    db = MlflowSettings.from_env().mlops_home / "storage" / "mlflow.db"
    connection = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    print(f"SQLite backend store (read-only): {db}\n")
    existing = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    print(f"{len(existing)} tables. Row counts of the main ones:")
    for table in TABLES:
        if table in existing:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<26} {count}")
    for title, sql in QUERIES.items():
        print(f"\n{title}:")
        for row in connection.execute(sql):
            print("  " + " | ".join(str(v) for v in row))
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
