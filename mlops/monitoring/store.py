"""Local monitoring history (SQLite under ARGOS_MLOPS_HOME). Stores AGGREGATES only: no copy
of the Core events.

- snapshots: one row per (scope, window, data kind), deterministic id; an explicit collection
  replaces it (late events are reconciled by recomputing the window, never duplicated);
- references: immutable (insert only; a new freeze = a new id);
- alerts: one row per alert key (model, version, scope, indicator); a persistent drift
  updates ``last_detected`` instead of creating a new alert; resolved when it disappears;
- collections: log of the explicit collections (GET requests never write).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (snapshot_id TEXT PRIMARY KEY, scope_key TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, data_kind TEXT NOT NULL,
  computed_at TEXT NOT NULL, partial INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS snapshots_scope ON snapshots(scope_key, window_start);
CREATE TABLE IF NOT EXISTS refs (reference_id TEXT PRIMARY KEY, model_key TEXT NOT NULL,
  created_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (alert_key TEXT PRIMARY KEY, model_key TEXT NOT NULL,
  state TEXT NOT NULL, first_detected TEXT NOT NULL, last_detected TEXT NOT NULL,
  resolved_at TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drift_windows (model_key TEXT NOT NULL, model_version TEXT NOT NULL,
  data_kind TEXT NOT NULL, window_day TEXT NOT NULL, computed_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (model_key, model_version, data_kind, window_day));
CREATE TABLE IF NOT EXISTS collections (collection_id TEXT PRIMARY KEY, at TEXT NOT NULL,
  payload TEXT NOT NULL);
"""


def default_path() -> Path:
    return (
        Path(os.environ.get("ARGOS_MLOPS_HOME", Path.home() / "ARGOS_MLOPS_LOCAL"))
        / "monitoring.sqlite"
    )


def snapshot_id(scope_key: str, start: str, end: str, kind: str) -> str:
    return hashlib.sha256(f"{scope_key}|{start}|{end}|{kind}".encode()).hexdigest()[:32]


class MonitoringStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or default_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    # ------------------------------------------------------------------ snapshots

    def upsert_snapshot(
        self,
        scope_key: str,
        start: str,
        end: str,
        kind: str,
        computed_at: str,
        partial: bool,
        payload: dict,
    ) -> str:
        sid = snapshot_id(scope_key, start, end, kind)
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                (sid, scope_key, start, end, kind, computed_at, int(partial), json.dumps(payload)),
            )
        return sid

    def snapshots(self, scope_key: str | None = None, kind: str | None = None) -> list[dict]:
        q, args = (
            "SELECT snapshot_id, scope_key, window_start, window_end, data_kind, computed_at, "
            "partial, payload FROM snapshots WHERE 1=1",
            [],
        )
        if scope_key:
            q, args = q + " AND scope_key=?", [*args, scope_key]
        if kind:
            q, args = q + " AND data_kind=?", [*args, kind]
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY window_start", args).fetchall()
        return [
            {
                "snapshot_id": r[0],
                "scope_key": r[1],
                "window_start": r[2],
                "window_end": r[3],
                "data_kind": r[4],
                "computed_at": r[5],
                "partial": bool(r[6]),
                **json.loads(r[7]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ references (immutable)

    def add_reference(
        self, reference_id: str, model_key: str, created_at: str, payload: dict
    ) -> None:
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO refs VALUES (?,?,?,?)",
                    (reference_id, model_key, created_at, json.dumps(payload)),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"reference {reference_id} already exists (references are immutable)"
                ) from exc

    def references(self, model_key: str | None = None) -> list[dict]:
        q, args = "SELECT payload FROM refs", []
        if model_key:
            q, args = q + " WHERE model_key=?", [model_key]
        with self._conn() as c:
            return [json.loads(r[0]) for r in c.execute(q + " ORDER BY created_at", args)]

    # ------------------------------------------------------------------ alerts

    def upsert_alert(self, key: str, model_key: str, now: str, payload: dict) -> None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT first_detected FROM alerts WHERE alert_key=?", (key,)
            ).fetchone()
            first = row[0] if row else now
            c.execute(
                "INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?)",
                (key, model_key, "open", first, now, None, json.dumps(payload)),
            )

    def resolve_missing(self, open_keys: set[str], now: str) -> int:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT alert_key FROM alerts WHERE state='open'").fetchall()
            gone = [r[0] for r in rows if r[0] not in open_keys]
            for key in gone:
                c.execute(
                    "UPDATE alerts SET state='resolved', resolved_at=? WHERE alert_key=?",
                    (now, key),
                )
        return len(gone)

    def alerts(self, state: str | None = None) -> list[dict]:
        q, args = (
            "SELECT alert_key, model_key, state, first_detected, last_detected, resolved_at, "
            "payload FROM alerts",
            [],
        )
        if state:
            q, args = q + " WHERE state=?", [state]
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY last_detected DESC", args).fetchall()
        return [
            {
                "alert_key": r[0],
                "model_key": r[1],
                "state": r[2],
                "first_detected": r[3],
                "last_detected": r[4],
                "resolved_at": r[5],
                **json.loads(r[6]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ drift windows

    def upsert_drift_window(
        self, key: str, version: str, kind: str, day: str, at: str, payload: dict
    ) -> None:
        """ONE row per distinct daily window: re-collecting a window replaces its result, so
        several collections of the same window are never several independent detections."""
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO drift_windows VALUES (?,?,?,?,?,?)",
                (key, version, kind, day, at, json.dumps(payload)),
            )

    def drift_windows(self, key: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT model_version, data_kind, window_day, computed_at, payload "
                "FROM drift_windows "
                "WHERE model_key=? ORDER BY window_day",
                (key,),
            ).fetchall()
        return [
            {
                "model_version": r[0],
                "data_kind": r[1],
                "window_day": r[2],
                "computed_at": r[3],
                **json.loads(r[4]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ collections

    def log_collection(self, collection_id: str, at: str, payload: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO collections VALUES (?,?,?)",
                (collection_id, at, json.dumps(payload)),
            )

    def collections(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            return [
                {"collection_id": r[0], "at": r[1], **json.loads(r[2])}
                for r in c.execute(
                    "SELECT collection_id, at, payload FROM collections ORDER BY at DESC LIMIT ?",
                    (limit,),
                )
            ]
