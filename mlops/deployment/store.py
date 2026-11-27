"""Durable operation journal; UC and Serving remain the model/config sources of truth."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from mlops.deployment.contracts import DecisionRecord, DeploymentOperation, LifecycleError

ACTIVE = ("prepared", "requesting", "updating", "verifying", "uncertain")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_path() -> Path:
    home = Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))
    return Path(os.environ.get("HOVIS_DEPLOYMENT_DB", home / "deployment_operations.sqlite3"))


class OperationStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                model_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                document TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_operation_per_endpoint
                ON operations(endpoint) WHERE status IN
                ('prepared','requesting','updating','verifying','uncertain');
            CREATE TABLE IF NOT EXISTS operation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                at TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT
            );
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                document TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def _begin(self) -> None:
        self.db.execute("BEGIN IMMEDIATE")

    def _event(self, operation_id: str, status: str, note: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO operation_events(operation_id,at,status,note) VALUES(?,?,?,?)",
            (operation_id, now(), status, note),
        )

    def insert(self, operation: DeploymentOperation) -> DeploymentOperation:
        with self._lock:
            self._begin()
            try:
                self.db.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,?)",
                    (
                        operation.operation_id,
                        operation.endpoint,
                        operation.model_id,
                        operation.status,
                        operation.created_at,
                        operation.model_dump_json(),
                    ),
                )
                self._event(operation.operation_id, operation.status)
                self.db.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self.db.execute("ROLLBACK")
                raise LifecycleError("another operation is active on this endpoint") from exc
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return operation

    def get(self, operation_id: str) -> DeploymentOperation:
        with self._lock:
            row = self.db.execute(
                "SELECT document FROM operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
        if row is None:
            raise LifecycleError("deployment operation not found", 404)
        return DeploymentOperation.model_validate_json(row[0])

    def list(self, endpoint: str | None = None, limit: int = 100) -> list[DeploymentOperation]:
        sql = "SELECT document FROM operations"
        args: tuple = ()
        if endpoint:
            sql += " WHERE endpoint=?"
            args = (endpoint,)
        with self._lock:
            rows = self.db.execute(
                sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [DeploymentOperation.model_validate_json(row[0]) for row in rows]

    def active(self, endpoint: str) -> DeploymentOperation | None:
        with self._lock:
            row = self.db.execute(
                "SELECT document FROM operations WHERE endpoint=? AND status IN "
                "('prepared','requesting','updating','verifying','uncertain')",
                (endpoint,),
            ).fetchone()
        return DeploymentOperation.model_validate_json(row[0]) if row else None

    def transition(
        self, operation_id: str, expected: set[str], status: str, note: str | None = None, **fields
    ) -> DeploymentOperation:
        with self._lock:
            self._begin()
            try:
                row = self.db.execute(
                    "SELECT document FROM operations WHERE operation_id=?", (operation_id,)
                ).fetchone()
                if row is None:
                    raise LifecycleError("deployment operation not found", 404)
                old = DeploymentOperation.model_validate_json(row[0])
                if old.status not in expected:
                    raise LifecycleError(f"operation is {old.status}; expected {sorted(expected)}")
                new = old.model_copy(update={"status": status, "updated_at": now(), **fields})
                self.db.execute(
                    "UPDATE operations SET status=?,document=? WHERE operation_id=?",
                    (status, new.model_dump_json(), operation_id),
                )
                self._event(operation_id, status, note)
                self.db.execute("COMMIT")
                return new
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def events(self, operation_id: str) -> list[dict]:
        self.get(operation_id)
        with self._lock:
            rows = self.db.execute(
                "SELECT at,status,note FROM operation_events WHERE operation_id=? "
                "ORDER BY event_id",
                (operation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def expire_prepared(self) -> None:
        with self._lock:
            ids = [
                row[0]
                for row in self.db.execute(
                    "SELECT operation_id FROM operations WHERE status='prepared' "
                    "AND json_extract(document,'$.expires_at') < ?",
                    (now(),),
                )
            ]
        for operation_id in ids:
            try:
                self.transition(
                    operation_id, {"prepared"}, "expired", "confirmation window expired"
                )
            except LifecycleError:
                pass

    def insert_decision(self, decision: DecisionRecord) -> DecisionRecord:
        with self._lock:
            self.db.execute(
                "INSERT INTO decisions VALUES(?,?,?,?,?)",
                (
                    decision.decision_id,
                    decision.model_id,
                    decision.version,
                    decision.created_at,
                    decision.model_dump_json(),
                ),
            )
        return decision

    def update_decision(self, decision_id: str, **fields) -> DecisionRecord:
        with self._lock:
            row = self.db.execute(
                "SELECT document FROM decisions WHERE decision_id=?", (decision_id,)
            ).fetchone()
            if row is None:
                raise LifecycleError("decision not found", 404)
            decision = DecisionRecord.model_validate_json(row[0]).model_copy(update=fields)
            self.db.execute(
                "UPDATE decisions SET document=? WHERE decision_id=?",
                (decision.model_dump_json(), decision_id),
            )
        return decision

    def decisions(self, model_id: str, version: str) -> list[DecisionRecord]:
        with self._lock:
            rows = self.db.execute(
                "SELECT document FROM decisions WHERE model_id=? AND version=? "
                "ORDER BY created_at DESC",
                (model_id, version),
            ).fetchall()
        return [DecisionRecord.model_validate_json(row[0]) for row in rows]
