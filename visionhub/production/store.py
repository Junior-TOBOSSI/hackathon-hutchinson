"""SQLite persistence of the Production Engine (parts, corrections, shifts).

Same database file as the inference events, with its own connection. Every write runs
in a ``BEGIN IMMEDIATE`` transaction, so a part and the inference event it references
are committed together or not at all.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from visionhub.contracts import Event
from visionhub.integration.edge_events import EdgeEvent, EdgeEventType, IngestAck
from visionhub.production.contracts import (
    AIPrediction,
    Correction,
    CorrectionIn,
    DispositionIn,
    InferenceError,
    Part,
    PartVerdict,
    Shift,
)
from visionhub.production.db import migrate
from visionhub.production.kpi import Tally
from visionhub.production.outbox import enqueue

PART_COLUMNS = (
    "part_id, station_id, cycle_id, shift_id, created_at, trigger_source, camera_id, "
    "image_sha256, predicted_verdict, prediction, error, event_id, effective_verdict, "
    "correction_count, disposition, disposition_note, disposition_updated_at"
)
SHIFT_COLUMNS = (
    "shift_id, station_id, name, status, started_at, planned_duration_min, target_parts, ended_at"
)
CORRECTION_COLUMNS = (
    "correction_id, part_id, sequence, previous_verdict, new_verdict, reason, actor_role, "
    "physical_inspection, at"
)


class ProductionError(Exception):
    """Base class of the business errors, mapped to HTTP codes by the router."""


class NotFoundError(ProductionError):
    pass


class ConflictError(ProductionError):
    pass


class DuplicateCycleError(ConflictError):
    pass


class InvalidOperationError(ProductionError):
    pass


class ProductionStore:
    def __init__(self, path: str = ":memory:", *, simulated_default: bool = False) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: transactions are opened explicitly (BEGIN IMMEDIATE).
        self._conn = sqlite3.connect(
            path, check_same_thread=False, timeout=10, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self.simulated_default = simulated_default
        with self._lock:
            self.migrations_applied = migrate(self._conn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _fetch(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ------------------------------------------------------------------ parts

    def insert_part(self, part: Part, event: Event | None) -> None:
        """Store a part and its inference event atomically.

        Raises DuplicateCycleError if (station_id, cycle_id) already exists.
        """
        with self._write() as conn:
            if event is not None:
                # Same row format as visionhub.store.EventStore.add.
                conn.execute(
                    "INSERT INTO events (event_id, ts, use_case, decision, feedback, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.frame.timestamp.isoformat(),
                        event.use_case.value,
                        event.decision.value,
                        int(event.operator_feedback is not None),
                        event.model_dump_json(),
                    ),
                )
            try:
                conn.execute(
                    f"INSERT INTO parts ({PART_COLUMNS}) VALUES ({', '.join('?' * 17)})",
                    (
                        part.part_id,
                        part.station_id,
                        part.cycle_id,
                        part.shift_id,
                        part.created_at.isoformat(),
                        part.trigger_source,
                        part.camera_id,
                        part.image_sha256,
                        part.predicted_verdict.value,
                        part.prediction.model_dump_json() if part.prediction else None,
                        part.error.model_dump_json() if part.error else None,
                        part.prediction.event_id if part.prediction else None,
                        part.effective_verdict.value,
                        part.correction_count,
                        part.disposition.value,
                        part.disposition_note,
                        None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateCycleError(
                    f"cycle {part.cycle_id!r} already exists on station {part.station_id!r}"
                ) from exc
            simulated = part.trigger_source == "plc_simulated"
            if event is not None:
                enqueue(
                    conn,
                    station_id=part.station_id,
                    event_type=EdgeEventType.INFERENCE,
                    payload={"kind": "inference", "event": event},
                    occurred_at=event.frame.timestamp,
                    simulated=simulated,
                    camera_id=part.camera_id,
                    cycle_id=part.cycle_id,
                    use_case=event.use_case,
                    model_name=event.model_name,
                    model_version=event.model_version,
                    score=event.score,
                    decision=event.decision,
                )
            enqueue(
                conn,
                station_id=part.station_id,
                event_type=EdgeEventType.PART_RECORDED,
                payload={"kind": "part.recorded", "part": part},
                occurred_at=part.created_at,
                simulated=simulated,
                camera_id=part.camera_id,
                cycle_id=part.cycle_id,
                part_id=part.part_id,
                use_case="quality",
                verdict=part.predicted_verdict,
            )

    def get_part(self, part_id: str) -> Part | None:
        rows = self._fetch(f"SELECT {PART_COLUMNS} FROM parts WHERE part_id = ?", (part_id,))
        return _part(rows[0]) if rows else None

    def get_part_by_cycle(self, station_id: str, cycle_id: str) -> Part | None:
        rows = self._fetch(
            f"SELECT {PART_COLUMNS} FROM parts WHERE station_id = ? AND cycle_id = ?",
            (station_id, cycle_id),
        )
        return _part(rows[0]) if rows else None

    def list_parts(
        self,
        station_id: str | None = None,
        shift_id: str | None = None,
        verdict: PartVerdict | None = None,
        limit: int = 50,
    ) -> list[Part]:
        """Most recent parts first."""
        where, params = _where(station_id=station_id, shift_id=shift_id)
        if verdict is not None:
            where += " AND effective_verdict = ?"
            params.append(verdict.value)
        rows = self._fetch(
            f"SELECT {PART_COLUMNS} FROM parts WHERE {where} "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            [*params, limit],
        )
        return [_part(r) for r in rows]

    def set_disposition(self, part_id: str, body: DispositionIn, at: datetime) -> Part:
        with self._write() as conn:
            row = conn.execute(
                "SELECT station_id, trigger_source FROM parts WHERE part_id = ?", (part_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"unknown part {part_id!r}")
            conn.execute(
                "UPDATE parts SET disposition = ?, disposition_note = ?, "
                "disposition_updated_at = ? WHERE part_id = ?",
                (body.disposition.value, body.note, at.isoformat(), part_id),
            )
            enqueue(
                conn,
                station_id=row["station_id"],
                event_type=EdgeEventType.PART_DISPOSITION,
                payload={
                    "kind": "part.disposition",
                    "part_id": part_id,
                    "disposition": body.disposition,
                    "note": body.note,
                },
                occurred_at=at,
                simulated=row["trigger_source"] == "plc_simulated",
                part_id=part_id,
            )
        return self.get_part(part_id)

    # ------------------------------------------------------------------ corrections

    def add_correction(
        self, part_id: str, body: CorrectionIn, correction_id: str, at: datetime
    ) -> tuple[Part, Correction]:
        """Append a human correction and update the effective verdict, atomically."""
        with self._write() as conn:
            row = conn.execute(
                "SELECT station_id, trigger_source, effective_verdict, correction_count "
                "FROM parts WHERE part_id = ?",
                (part_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"unknown part {part_id!r}")
            current = PartVerdict(row["effective_verdict"])
            if current != body.expected_current_verdict:
                raise ConflictError(
                    f"part verdict is {current.value}, not {body.expected_current_verdict.value}:"
                    " reload the part before correcting it"
                )
            if body.new_verdict == current.value:
                raise InvalidOperationError(f"part verdict is already {current.value}")
            if current in (PartVerdict.HOLD, PartVerdict.ERROR) and not body.physical_inspection:
                raise InvalidOperationError(
                    f"a {current.value} part can only be corrected after a physical inspection"
                    " (physical_inspection=true)"
                )
            correction = Correction(
                correction_id=correction_id,
                part_id=part_id,
                sequence=row["correction_count"] + 1,
                previous_verdict=current,
                new_verdict=body.new_verdict,
                reason=body.reason,
                actor_role=body.actor_role,
                physical_inspection=body.physical_inspection,
                at=at,
            )
            conn.execute(
                f"INSERT INTO corrections ({CORRECTION_COLUMNS}) VALUES ({', '.join('?' * 9)})",
                (
                    correction.correction_id,
                    part_id,
                    correction.sequence,
                    correction.previous_verdict.value,
                    correction.new_verdict,
                    correction.reason,
                    correction.actor_role,
                    int(correction.physical_inspection),
                    at.isoformat(),
                ),
            )
            conn.execute(
                "UPDATE parts SET effective_verdict = ?, correction_count = ? WHERE part_id = ?",
                (correction.new_verdict, correction.sequence, part_id),
            )
            enqueue(
                conn,
                station_id=row["station_id"],
                event_type=EdgeEventType.PART_CORRECTED,
                payload={"kind": "part.corrected", "correction": correction},
                occurred_at=at,
                simulated=row["trigger_source"] == "plc_simulated",
                part_id=part_id,
                verdict=PartVerdict(correction.new_verdict),
            )
        return self.get_part(part_id), correction

    def list_corrections(self, part_id: str) -> list[Correction]:
        if self.get_part(part_id) is None:
            raise NotFoundError(f"unknown part {part_id!r}")
        rows = self._fetch(
            f"SELECT {CORRECTION_COLUMNS} FROM corrections WHERE part_id = ? ORDER BY sequence",
            (part_id,),
        )
        return [
            Correction(**{**dict(r), "physical_inspection": bool(r["physical_inspection"])})
            for r in rows
        ]

    # ------------------------------------------------------------------ shifts

    def insert_shift(self, shift: Shift) -> None:
        try:
            with self._write() as conn:
                conn.execute(
                    f"INSERT INTO shifts ({SHIFT_COLUMNS}) VALUES ({', '.join('?' * 8)})",
                    (
                        shift.shift_id,
                        shift.station_id,
                        shift.name,
                        shift.status,
                        shift.started_at.isoformat(),
                        shift.planned_duration_min,
                        shift.target_parts,
                        None,
                    ),
                )
                enqueue(
                    conn,
                    station_id=shift.station_id,
                    event_type=EdgeEventType.SHIFT_OPENED,
                    payload={"kind": "shift", "shift": shift},
                    occurred_at=shift.started_at,
                    simulated=self.simulated_default,
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"a shift is already open on station {shift.station_id!r}") from exc

    def close_shift(self, shift_id: str, at: datetime) -> Shift:
        with self._write() as conn:
            row = conn.execute(
                f"SELECT {SHIFT_COLUMNS} FROM shifts WHERE shift_id = ?", (shift_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"unknown shift {shift_id!r}")
            if row["status"] != "OPEN":
                raise ConflictError(f"shift {shift_id!r} is already closed")
            conn.execute(
                "UPDATE shifts SET status = 'CLOSED', ended_at = ? WHERE shift_id = ?",
                (at.isoformat(), shift_id),
            )
            closed = Shift(**{**dict(row), "status": "CLOSED", "ended_at": at})
            enqueue(
                conn,
                station_id=closed.station_id,
                event_type=EdgeEventType.SHIFT_CLOSED,
                payload={"kind": "shift", "shift": closed},
                occurred_at=at,
                simulated=self.simulated_default,
            )
        return self.get_shift(shift_id)

    # ------------------------------------------------------------------ durable Edge -> Core outbox

    def pending_events(self, limit: int = 100) -> list[EdgeEvent]:
        """Return one station's earliest pending events, preserving its sequence order."""
        rows = self._fetch(
            "SELECT station_id, payload FROM outbox WHERE delivered_at IS NULL AND rejected = 0 "
            "ORDER BY station_id, edge_sequence LIMIT ?",
            (limit,),
        )
        if not rows:
            return []
        station = rows[0]["station_id"]
        return [
            EdgeEvent.model_validate_json(row["payload"])
            for row in rows
            if row["station_id"] == station
        ]

    def mark_ack(self, ack: IngestAck, sent: list[EdgeEvent]) -> None:
        expected = {event.event_id for event in sent}
        received = [result.event_id for result in ack.results]
        if (
            not sent
            or ack.station_id != sent[0].station_id
            or len(received) != len(expected)
            or set(received) != expected
        ):
            raise ValueError("Core ACK does not match the sent batch")
        delivered_at = datetime.now(UTC).isoformat()
        with self._write() as conn:
            for result in ack.results:
                delivered = result.status in ("accepted", "duplicate")
                updated = conn.execute(
                    "UPDATE outbox SET attempts = attempts + 1, delivered_at = ?, "
                    "rejected = ?, last_error = ? WHERE event_id = ? AND delivered_at IS NULL",
                    (
                        delivered_at if delivered else None,
                        int(result.status == "rejected"),
                        result.error if not delivered else None,
                        result.event_id,
                    ),
                ).rowcount
                if updated != 1:
                    raise ValueError("Core ACK references a missing or delivered event")

    def mark_failure(self, sent: list[EdgeEvent], error: str) -> None:
        with self._write() as conn:
            for event in sent:
                conn.execute(
                    "UPDATE outbox SET attempts = attempts + 1, last_error = ? "
                    "WHERE event_id = ? AND delivered_at IS NULL",
                    (error[:500], event.event_id),
                )

    def outbox_status(self) -> dict[str, int | str | None]:
        row = self._fetch(
            "SELECT COUNT(*) AS total, "
            "SUM(delivered_at IS NULL AND rejected = 0) AS pending, "
            "SUM(delivered_at IS NOT NULL) AS delivered, SUM(rejected) AS rejected "
            "FROM outbox"
        )[0]
        error = self._fetch(
            "SELECT last_error FROM outbox WHERE delivered_at IS NULL AND last_error IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        )
        return {
            "total": row["total"],
            "pending": row["pending"] or 0,
            "delivered": row["delivered"] or 0,
            "rejected": row["rejected"] or 0,
            "last_error": error[0][0] if error else None,
        }

    def get_shift(self, shift_id: str) -> Shift | None:
        rows = self._fetch(f"SELECT {SHIFT_COLUMNS} FROM shifts WHERE shift_id = ?", (shift_id,))
        return Shift(**dict(rows[0])) if rows else None

    def current_shift(self, station_id: str) -> Shift | None:
        rows = self._fetch(
            f"SELECT {SHIFT_COLUMNS} FROM shifts WHERE station_id = ? AND status = 'OPEN'",
            (station_id,),
        )
        return Shift(**dict(rows[0])) if rows else None

    def list_shifts(self, station_id: str | None = None, limit: int = 50) -> list[Shift]:
        where, params = _where(station_id=station_id)
        rows = self._fetch(
            f"SELECT {SHIFT_COLUMNS} FROM shifts WHERE {where} ORDER BY started_at DESC LIMIT ?",
            [*params, limit],
        )
        return [Shift(**dict(r)) for r in rows]

    # ------------------------------------------------------------------ KPI input

    def tally(
        self,
        *,
        shift_id: str | None = None,
        station_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Tally:
        """Counts of the parts matching the filters, read in one consistent snapshot."""
        where, params = _where(station_id=station_id, shift_id=shift_id)
        if start is not None:
            where += " AND created_at >= ?"
            params.append(start.isoformat())
        if end is not None:
            where += " AND created_at < ?"
            params.append(end.isoformat())
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                eff = self._conn.execute(
                    f"SELECT effective_verdict, COUNT(*) FROM parts WHERE {where} "
                    "GROUP BY effective_verdict",
                    params,
                ).fetchall()
                pred = self._conn.execute(
                    f"SELECT predicted_verdict, COUNT(*) FROM parts WHERE {where} "
                    "GROUP BY predicted_verdict",
                    params,
                ).fetchall()
                corrected, latency = self._conn.execute(
                    "SELECT COALESCE(SUM(correction_count > 0), 0), "
                    f"AVG(json_extract(prediction, '$.latency_ms')) FROM parts WHERE {where}",
                    params,
                ).fetchone()
            finally:
                self._conn.execute("COMMIT")
        return Tally(
            effective={PartVerdict(v): n for v, n in eff},
            predicted={PartVerdict(v): n for v, n in pred},
            corrected=corrected,
            mean_latency_ms=latency,
        )


def _where(**filters: str | None) -> tuple[str, list]:
    clause, params = "1=1", []
    for column, value in filters.items():
        if value is not None:
            clause += f" AND {column} = ?"
            params.append(value)
    return clause, params


def _part(row: sqlite3.Row) -> Part:
    data = dict(row)
    data.pop("event_id")
    data["prediction"] = (
        AIPrediction.model_validate_json(data["prediction"]) if data["prediction"] else None
    )
    data["error"] = InferenceError.model_validate_json(data["error"]) if data["error"] else None
    return Part(**data)
