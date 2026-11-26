"""Non-destructive, versioned SQLite migrations of the Production Engine.

The production tables live in the same SQLite file as the inference ``events`` table.
Rules: migrations only ADD objects (``CREATE ... IF NOT EXISTS``); they never drop,
rename or rewrite existing tables. Each migration runs in its own transaction and is
recorded in ``schema_migrations``.

Database-level guarantees (triggers):
- the original prediction of a part (and its identity) can never be updated;
- parts can never be deleted;
- corrections are append-only (no UPDATE, no DELETE).
"""

from __future__ import annotations

import sqlite3

from visionhub.contracts import utc_now
from visionhub.store import SCHEMA as EVENTS_SCHEMA

MIGRATION_0001 = """
CREATE TABLE IF NOT EXISTS shifts (
    shift_id             TEXT PRIMARY KEY,
    station_id           TEXT NOT NULL,
    name                 TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
    started_at           TEXT NOT NULL,
    planned_duration_min INTEGER NOT NULL CHECK (planned_duration_min > 0),
    target_parts         INTEGER NOT NULL CHECK (target_parts >= 0),
    ended_at             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_shifts_one_open_per_station
    ON shifts (station_id) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS ix_shifts_station_started ON shifts (station_id, started_at);

CREATE TABLE IF NOT EXISTS parts (
    part_id                TEXT PRIMARY KEY,
    station_id             TEXT NOT NULL,
    cycle_id               TEXT NOT NULL,
    shift_id               TEXT REFERENCES shifts (shift_id),
    created_at             TEXT NOT NULL,
    trigger_source         TEXT NOT NULL,
    camera_id              TEXT NOT NULL,
    image_sha256           TEXT,
    predicted_verdict      TEXT NOT NULL CHECK (predicted_verdict IN ('OK','NOK','HOLD','ERROR')),
    prediction             TEXT,
    error                  TEXT,
    event_id               TEXT,
    effective_verdict      TEXT NOT NULL CHECK (effective_verdict IN ('OK','NOK','HOLD','ERROR')),
    correction_count       INTEGER NOT NULL DEFAULT 0,
    disposition            TEXT NOT NULL DEFAULT 'UNKNOWN',
    disposition_note       TEXT,
    disposition_updated_at TEXT,
    UNIQUE (station_id, cycle_id)
);
CREATE INDEX IF NOT EXISTS ix_parts_shift ON parts (shift_id);
CREATE INDEX IF NOT EXISTS ix_parts_station_created ON parts (station_id, created_at);

CREATE TABLE IF NOT EXISTS corrections (
    correction_id       TEXT PRIMARY KEY,
    part_id             TEXT NOT NULL REFERENCES parts (part_id),
    sequence            INTEGER NOT NULL,
    previous_verdict    TEXT NOT NULL,
    new_verdict         TEXT NOT NULL CHECK (new_verdict IN ('OK', 'NOK')),
    reason              TEXT NOT NULL,
    actor_role          TEXT NOT NULL,
    physical_inspection INTEGER NOT NULL,
    at                  TEXT NOT NULL,
    UNIQUE (part_id, sequence)
);

CREATE TRIGGER IF NOT EXISTS trg_parts_prediction_immutable
BEFORE UPDATE ON parts
WHEN NEW.part_id IS NOT OLD.part_id
  OR NEW.station_id IS NOT OLD.station_id
  OR NEW.cycle_id IS NOT OLD.cycle_id
  OR NEW.shift_id IS NOT OLD.shift_id
  OR NEW.created_at IS NOT OLD.created_at
  OR NEW.trigger_source IS NOT OLD.trigger_source
  OR NEW.camera_id IS NOT OLD.camera_id
  OR NEW.image_sha256 IS NOT OLD.image_sha256
  OR NEW.predicted_verdict IS NOT OLD.predicted_verdict
  OR NEW.prediction IS NOT OLD.prediction
  OR NEW.error IS NOT OLD.error
  OR NEW.event_id IS NOT OLD.event_id
BEGIN
    SELECT RAISE(ABORT, 'parts: the original prediction and identity are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_parts_no_delete
BEFORE DELETE ON parts
BEGIN
    SELECT RAISE(ABORT, 'parts: deletion is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_corrections_no_update
BEFORE UPDATE ON corrections
BEGIN
    SELECT RAISE(ABORT, 'corrections: history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_corrections_no_delete
BEFORE DELETE ON corrections
BEGIN
    SELECT RAISE(ABORT, 'corrections: history is append-only');
END;
"""

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "production_core", MIGRATION_0001),
    (
        2,
        "edge_outbox",
        """
CREATE TABLE IF NOT EXISTS outbox (
    event_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL,
    edge_sequence INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    rejected INTEGER NOT NULL DEFAULT 0,
    UNIQUE (station_id, edge_sequence)
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending
    ON outbox (delivered_at, rejected, station_id, edge_sequence);
""",
    ),
]


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply the missing migrations; return the versions applied by this call.

    ``conn`` must be in autocommit mode (``isolation_level=None``).
    """
    # The inference events table: same statement as EventStore, idempotent.
    conn.executescript(EVENTS_SCHEMA)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = []
    for version, name, sql in MIGRATIONS:
        if version in applied_versions(conn):
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-check inside the write lock: another process may have just applied it.
            if version not in applied_versions(conn):
                for statement in _split(sql):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, utc_now().isoformat()),
                )
                applied.append(version)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return applied


def _split(script: str) -> list[str]:
    """Split a script into complete statements (trigger bodies contain ';')."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        raise ValueError(f"Incomplete SQL statement in migration: {buffer!r}")
    return statements
