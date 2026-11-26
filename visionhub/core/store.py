"""Durable Edge event inbox and rebuildable industrial projections."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from visionhub.contracts import UseCase, utc_now
from visionhub.integration.core_api import Alert, OperatorReport, StationSummary
from visionhub.integration.edge_events import (
    EdgeEvent,
    EdgeEventBatch,
    EdgeEventType,
    IngestAck,
    IngestResult,
)
from visionhub.integration.mlops import ModelRef, StationDeploymentStatus
from visionhub.production.contracts import (
    Correction,
    Part,
    PartVerdict,
    ProductionKPI,
    Shift,
    ShiftReport,
)
from visionhub.production.kpi import Tally, compute_kpi


class CoreStorageError(Exception):
    """The batch could not be durably committed."""


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc_iso(value: datetime) -> str:
    """Treat a legacy naive payload timestamp as UTC; index all times consistently."""
    return (
        value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    ).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, edge_sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, document TEXT NOT NULL,
    UNIQUE(station_id, edge_sequence)
);
CREATE INDEX IF NOT EXISTS events_station_time ON events(station_id, occurred_at);
CREATE TABLE IF NOT EXISTS stations (
    station_id TEXT PRIMARY KEY, simulated INTEGER NOT NULL, last_seen_at TEXT NOT NULL,
    last_cycle_at TEXT
);
CREATE TABLE IF NOT EXISTS parts (
    part_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, cycle_id TEXT NOT NULL,
    shift_id TEXT, created_at TEXT NOT NULL, document TEXT NOT NULL,
    UNIQUE(station_id, cycle_id)
);
CREATE INDEX IF NOT EXISTS parts_station_time ON parts(station_id, created_at);
CREATE TABLE IF NOT EXISTS corrections (
    correction_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, part_id TEXT NOT NULL,
    sequence INTEGER NOT NULL, document TEXT NOT NULL, UNIQUE(part_id, sequence)
);
CREATE TABLE IF NOT EXISTS shifts (
    shift_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, started_at TEXT NOT NULL,
    status TEXT NOT NULL, document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shifts_station ON shifts(station_id, status, started_at);
CREATE TABLE IF NOT EXISTS equipment (
    station_id TEXT NOT NULL, equipment_id TEXT NOT NULL, document TEXT NOT NULL,
    PRIMARY KEY(station_id, equipment_id)
);
CREATE TABLE IF NOT EXISTS models (
    station_id TEXT NOT NULL, use_case TEXT NOT NULL, document TEXT NOT NULL,
    occurred_at TEXT NOT NULL, PRIMARY KEY(station_id, use_case)
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, station_id TEXT NOT NULL, alert_key TEXT NOT NULL,
    status TEXT NOT NULL, last_seen_at TEXT NOT NULL, document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_active ON alerts(station_id, alert_key, status);
"""


class CoreStore:
    """A single SQLite writer guarded by a lock; projections are derived from the inbox."""

    def __init__(
        self, path: str, *, stale_after_s: int = 120, alert_on_review: bool = True
    ) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False, timeout=10
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()
        self.stale_after_s = stale_after_s
        self.alert_on_review = alert_on_review
        # This is also a recovery path after a previous process stopped mid-projection.
        with self._write() as conn:
            for row in conn.execute("SELECT DISTINCT station_id FROM events"):
                self._rebuild_station(conn, row["station_id"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def ingest(self, batch: EdgeEventBatch) -> IngestAck:
        """Commit inbox, projections and alerts together; return an ACK only after commit."""
        results: list[IngestResult] = []
        accepted: list[EdgeEvent] = []
        try:
            with self._write() as conn:
                for event in batch.events:
                    document = event.model_dump_json()
                    existing = conn.execute(
                        "SELECT document FROM events WHERE event_id=?", (event.event_id,)
                    ).fetchone()
                    if existing:
                        status = "duplicate" if existing["document"] == document else "rejected"
                        error = None if status == "duplicate" else "event_id has different content"
                    elif conn.execute(
                        "SELECT 1 FROM events WHERE station_id=? AND edge_sequence=?",
                        (event.station_id, event.edge_sequence),
                    ).fetchone():
                        status, error = "rejected", "edge_sequence already has another event"
                    else:
                        error = self._semantic_error(conn, event)
                        status = "rejected" if error else "accepted"
                        if not error:
                            conn.execute(
                                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    event.event_id,
                                    event.station_id,
                                    event.edge_sequence,
                                    event.event_type.value,
                                    event.occurred_at.isoformat(),
                                    document,
                                ),
                            )
                            accepted.append(event)
                    results.append(
                        IngestResult(event_id=event.event_id, status=status, error=error)
                    )
                if accepted:
                    self._rebuild_station(conn, batch.station_id)
                    for event in accepted:
                        self._observe_alert(conn, event)
                highest = self._highest_contiguous(conn, batch.station_id)
        except (sqlite3.Error, ValueError) as exc:
            raise CoreStorageError("Core could not persist the batch") from exc
        return IngestAck(
            station_id=batch.station_id,
            received_at=utc_now(),
            results=results,
            highest_contiguous_sequence=highest,
        )

    @staticmethod
    def _semantic_error(conn: sqlite3.Connection, event: EdgeEvent) -> str | None:
        payload = event.payload
        if event.event_type == EdgeEventType.PART_RECORDED:
            if payload.part.station_id != event.station_id:
                return "part station differs from envelope"
            if event.part_id and event.part_id != payload.part.part_id:
                return "part_id differs from payload"
            for row in conn.execute("SELECT document FROM events WHERE event_type='part.recorded'"):
                previous = EdgeEvent.model_validate_json(row[0]).payload.part
                if previous.part_id == payload.part.part_id:
                    return "part_id already belongs to another event"
                if (
                    previous.station_id == payload.part.station_id
                    and previous.cycle_id == payload.part.cycle_id
                ):
                    return "cycle already belongs to another event"
        if event.event_type in (EdgeEventType.SHIFT_OPENED, EdgeEventType.SHIFT_CLOSED):
            if payload.shift.station_id != event.station_id:
                return "shift station differs from envelope"
        if event.event_type == EdgeEventType.PART_CORRECTED:
            if event.part_id and event.part_id != payload.correction.part_id:
                return "part_id differs from payload"
            for row in conn.execute(
                "SELECT document FROM events WHERE event_type='part.corrected'"
            ):
                previous = EdgeEvent.model_validate_json(row[0]).payload.correction
                if previous.correction_id == payload.correction.correction_id:
                    return "correction_id already belongs to another event"
                if (
                    previous.part_id == payload.correction.part_id
                    and previous.sequence == payload.correction.sequence
                ):
                    return "correction sequence already belongs to another event"
        if event.event_type == EdgeEventType.INFERENCE:
            if payload.event.frame.workstation_id != event.station_id:
                return "inference station differs from envelope"
        return None

    @staticmethod
    def _highest_contiguous(conn: sqlite3.Connection, station_id: str) -> int:
        result = 0
        for row in conn.execute(
            "SELECT edge_sequence FROM events WHERE station_id=? ORDER BY edge_sequence",
            (station_id,),
        ):
            if row[0] != result + 1:
                break
            result += 1
        return result

    def _rebuild_station(self, conn: sqlite3.Connection, station_id: str) -> None:
        """Replay by Edge sequence so late parts and corrections converge to the same state."""
        events = [
            EdgeEvent.model_validate_json(row[0])
            for row in conn.execute(
                "SELECT document FROM events WHERE station_id=? ORDER BY edge_sequence",
                (station_id,),
            )
        ]
        for table in (
            "stations",
            "parts",
            "corrections",
            "shifts",
            "equipment",
            "models",
            "reports",
        ):
            conn.execute(f"DELETE FROM {table} WHERE station_id=?", (station_id,))
        if not events:
            return
        parts: dict[str, Part] = {}
        corrections: dict[str, dict[int, Correction]] = defaultdict(dict)
        dispositions: dict[str, tuple[datetime, object]] = {}
        shifts: dict[str, Shift] = {}
        equipment: dict[str, tuple[datetime, object]] = {}
        models: dict[str, tuple[datetime, object]] = {}
        reports: dict[str, OperatorReport] = {}
        for event in events:
            payload = event.payload
            if event.event_type == EdgeEventType.PART_RECORDED:
                parts.setdefault(payload.part.part_id, payload.part)
            elif event.event_type == EdgeEventType.PART_CORRECTED:
                correction = payload.correction
                corrections[correction.part_id][correction.sequence] = correction
            elif event.event_type == EdgeEventType.PART_DISPOSITION:
                previous = dispositions.get(payload.part_id)
                if previous is None or event.occurred_at >= previous[0]:
                    dispositions[payload.part_id] = (event.occurred_at, payload)
            elif event.event_type in (EdgeEventType.SHIFT_OPENED, EdgeEventType.SHIFT_CLOSED):
                shift = payload.shift
                previous = shifts.get(shift.shift_id)
                if previous is None or shift.status == "CLOSED":
                    shifts[shift.shift_id] = shift
            elif event.event_type == EdgeEventType.EQUIPMENT_STATUS:
                previous = equipment.get(payload.equipment_id)
                if previous is None or event.occurred_at >= previous[0]:
                    equipment[payload.equipment_id] = (event.occurred_at, payload)
            elif event.event_type == EdgeEventType.MODEL_STATUS:
                key = payload.use_case.value
                previous = models.get(key)
                if previous is None or event.occurred_at >= previous[0]:
                    models[key] = (event.occurred_at, payload)
            elif event.event_type == EdgeEventType.OPERATOR_REPORT:
                reports[payload.report_id] = OperatorReport(
                    **payload.model_dump(),
                    station_id=station_id,
                    created_at=event.occurred_at,
                )
        last_seen = max(event.occurred_at for event in events)
        last_cycle = max((part.created_at for part in parts.values()), default=None)
        conn.execute(
            "INSERT INTO stations VALUES (?, ?, ?, ?)",
            (
                station_id,
                int(all(event.simulated for event in events)),
                last_seen.isoformat(),
                last_cycle.isoformat() if last_cycle else None,
            ),
        )
        for part in parts.values():
            history = corrections.get(part.part_id, {})
            latest = history[max(history)] if history else None
            disposition = dispositions.get(part.part_id)
            changes = {
                "effective_verdict": latest.new_verdict if latest else part.effective_verdict,
                "correction_count": max(part.correction_count, max(history, default=0)),
            }
            if disposition:
                changes.update(
                    disposition=disposition[1].disposition,
                    disposition_note=disposition[1].note,
                    disposition_updated_at=disposition[0],
                )
            projected = Part.model_validate({**part.model_dump(), **changes})
            conn.execute(
                "INSERT INTO parts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    part.part_id,
                    station_id,
                    part.cycle_id,
                    part.shift_id,
                    _utc_iso(part.created_at),
                    projected.model_dump_json(),
                ),
            )
        for part_id, history in corrections.items():
            for correction in history.values():
                conn.execute(
                    "INSERT INTO corrections VALUES (?, ?, ?, ?, ?)",
                    (
                        correction.correction_id,
                        station_id,
                        part_id,
                        correction.sequence,
                        correction.model_dump_json(),
                    ),
                )
        for shift in shifts.values():
            conn.execute(
                "INSERT INTO shifts VALUES (?, ?, ?, ?, ?)",
                (
                    shift.shift_id,
                    station_id,
                    _utc_iso(shift.started_at),
                    shift.status,
                    shift.model_dump_json(),
                ),
            )
        for equipment_id, (_, payload) in equipment.items():
            conn.execute(
                "INSERT INTO equipment VALUES (?, ?, ?)",
                (station_id, equipment_id, payload.model_dump_json()),
            )
        for use_case, (when, payload) in models.items():
            conn.execute(
                "INSERT INTO models VALUES (?, ?, ?, ?)",
                (station_id, use_case, payload.model_dump_json(), when.isoformat()),
            )
        for report in reports.values():
            conn.execute(
                "INSERT INTO reports VALUES (?, ?, ?)",
                (report.report_id, station_id, report.model_dump_json()),
            )

    def _alert_observation(self, event: EdgeEvent) -> tuple[str, str, str] | None:
        if event.event_type == EdgeEventType.INFERENCE:
            finding = event.payload.event
            if finding.decision.value == "conforme":
                return None
            if finding.decision.value == "a_verifier" and not self.alert_on_review:
                return None
            severity = "critical" if finding.decision.value == "anomalie" else "warning"
            return (
                f"{finding.use_case.value}.decision",
                severity,
                f"{finding.use_case.value} detection",
            )
        if event.event_type == EdgeEventType.PART_RECORDED:
            verdict = event.payload.part.predicted_verdict
            if verdict == PartVerdict.OK:
                return None
            severity = "critical" if verdict == PartVerdict.ERROR else "warning"
            return f"part.{verdict.value.lower()}", severity, f"Quality part {verdict.value}"
        if event.event_type == EdgeEventType.EQUIPMENT_STATUS:
            item = event.payload
            if item.status == "ok":
                return None
            severity = "critical" if item.status == "down" else "warning"
            return (
                f"equipment.{item.equipment_id}",
                severity,
                f"{item.equipment_type} {item.status}",
            )
        if event.event_type == EdgeEventType.OPERATOR_REPORT:
            item = event.payload
            return f"report.{item.report_id}", item.severity, item.message
        return None

    def _observe_alert(self, conn: sqlite3.Connection, event: EdgeEvent) -> None:
        observation = self._alert_observation(event)
        if observation is None:
            return
        kind, severity, title = observation
        key = _json([event.station_id, event.camera_id, event.use_case, kind])
        row = conn.execute(
            "SELECT document FROM alerts WHERE station_id=? AND alert_key=? "
            "AND status IN ('open','acknowledged','validated') ORDER BY last_seen_at DESC LIMIT 1",
            (event.station_id, key),
        ).fetchone()
        if row:
            old = Alert.model_validate_json(row[0])
            alert = old.model_copy(
                update={
                    "first_seen_at": min(old.first_seen_at, event.occurred_at),
                    "last_seen_at": max(old.last_seen_at, event.occurred_at),
                    "occurrences": old.occurrences + 1,
                    "max_score": max(
                        [x for x in (old.max_score, event.score) if x is not None], default=None
                    ),
                    "source_event_ids": [*old.source_event_ids, event.event_id],
                    "severity": max(
                        (old.severity, severity),
                        key={"info": 0, "warning": 1, "critical": 2}.get,
                    ),
                }
            )
            conn.execute(
                "UPDATE alerts SET last_seen_at=?, document=? WHERE alert_id=?",
                (alert.last_seen_at.isoformat(), alert.model_dump_json(), alert.alert_id),
            )
        else:
            alert = Alert(
                alert_id=event.event_id,
                station_id=event.station_id,
                camera_id=event.camera_id,
                use_case=event.use_case,
                alert_type=kind,
                severity=severity,
                status="open",
                title=title,
                first_seen_at=event.occurred_at,
                last_seen_at=event.occurred_at,
                occurrences=1,
                max_score=event.score,
                source_event_ids=[event.event_id],
                simulated=event.simulated,
            )
            conn.execute(
                "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    alert.alert_id,
                    event.station_id,
                    key,
                    alert.status,
                    alert.last_seen_at.isoformat(),
                    alert.model_dump_json(),
                ),
            )

    def change_alert(self, alert_id: str, action: str) -> Alert | None:
        allowed = {
            "acknowledge": ("open",),
            "validate": ("open", "acknowledged"),
            "reject": ("open", "acknowledged"),
            "resolve": ("open", "acknowledged", "validated"),
        }
        with self._write() as conn:
            row = conn.execute(
                "SELECT document FROM alerts WHERE alert_id=?", (alert_id,)
            ).fetchone()
            if row is None:
                return None
            alert = Alert.model_validate_json(row[0])
            if alert.status not in allowed[action]:
                raise ValueError(f"cannot {action} an alert in status {alert.status}")
            status = (
                "acknowledged"
                if action == "acknowledge"
                else (
                    "validated"
                    if action == "validate"
                    else "rejected"
                    if action == "reject"
                    else "resolved"
                )
            )
            alert = alert.model_copy(update={"status": status})
            conn.execute(
                "UPDATE alerts SET status=?, document=? WHERE alert_id=?",
                (status, alert.model_dump_json(), alert_id),
            )
            return alert

    def health(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "status": "ok",
                "stations": self._conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0],
                "events": self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "parts": self._conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0],
            }

    def station(self, station_id: str, *, now: datetime | None = None) -> StationSummary | None:
        now = now or utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM stations WHERE station_id=?", (station_id,)
            ).fetchone()
            if row is None:
                return None
            shift_row = self._conn.execute(
                "SELECT document FROM shifts WHERE station_id=? AND status='OPEN' "
                "ORDER BY started_at DESC LIMIT 1",
                (station_id,),
            ).fetchone()
            shift = Shift.model_validate_json(shift_row[0]) if shift_row else None
            shift_report = self.shift_report(shift, now=now) if shift else None
            equipment = [
                json.loads(r[0])
                for r in self._conn.execute(
                    "SELECT document FROM equipment WHERE station_id=? ORDER BY equipment_id",
                    (station_id,),
                )
            ]
            models = []
            for model_row in self._conn.execute(
                "SELECT document, occurred_at FROM models WHERE station_id=? ORDER BY use_case",
                (station_id,),
            ):
                data = json.loads(model_row[0])
                # ModelRef requires an immutable numeric registry version. An Edge may
                # report a local semantic version; it remains visible in /model-status.
                model = None
                if data["model_version"].isdigit():
                    model = ModelRef(
                        registered_model=data["model_name"], version=data["model_version"]
                    )
                models.append(
                    StationDeploymentStatus(
                        station_id=station_id,
                        use_case=UseCase(data["use_case"]),
                        status="loaded" if data["loaded"] else "failed",
                        model=model,
                        loaded_at=_dt(model_row[1]) if data["loaded"] else None,
                        error=data["error"],
                    )
                )
            open_alerts = self._conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE station_id=? "
                "AND status IN ('open','acknowledged','validated')",
                (station_id,),
            ).fetchone()[0]
        last_seen = _dt(row["last_seen_at"])
        return StationSummary(
            station_id=station_id,
            name=station_id,
            cell=station_id.split("-")[0],
            simulated=bool(row["simulated"]),
            online=timedelta(0) <= now - last_seen <= timedelta(seconds=self.stale_after_s),
            last_seen_at=last_seen,
            current_shift=shift_report,
            equipment=equipment,
            models=models,
            open_alerts=open_alerts,
        )

    def stations(self, *, now: datetime | None = None) -> list[StationSummary]:
        with self._lock:
            ids = [
                r[0]
                for r in self._conn.execute("SELECT station_id FROM stations ORDER BY station_id")
            ]
        return [self.station(station_id, now=now) for station_id in ids]

    def shift_report(self, shift: Shift, *, now: datetime | None = None) -> ShiftReport:
        now = now or utc_now()
        return ShiftReport(
            shift=shift,
            kpi=self.kpi(
                shift.started_at,
                shift.ended_at or now,
                shift_id=shift.shift_id,
                target_parts=shift.target_parts,
                planned_duration_min=shift.planned_duration_min,
                now=now,
            ),
        )

    def kpi(
        self,
        start: datetime,
        end: datetime,
        *,
        station_id: str | None = None,
        shift_id: str | None = None,
        target_parts: int | None = None,
        planned_duration_min: int | None = None,
        now: datetime | None = None,
    ) -> ProductionKPI:
        if end < start:
            raise ValueError("from must be no later than to")
        sql = "SELECT document FROM parts WHERE created_at>=? AND created_at<?"
        params: list[str] = [start.isoformat(), end.isoformat()]
        if station_id is not None:
            sql += " AND station_id=?"
            params.append(station_id)
        if shift_id is not None:
            sql += " AND shift_id=?"
            params.append(shift_id)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        parts = [Part.model_validate_json(row[0]) for row in rows]
        tally = Tally()
        latencies = []
        for part in parts:
            tally.effective[part.effective_verdict] = (
                tally.effective.get(part.effective_verdict, 0) + 1
            )
            tally.predicted[part.predicted_verdict] = (
                tally.predicted.get(part.predicted_verdict, 0) + 1
            )
            tally.corrected += int(part.correction_count > 0)
            if part.prediction:
                latencies.append(part.prediction.latency_ms)
        tally.mean_latency_ms = sum(latencies) / len(latencies) if latencies else None
        return compute_kpi(
            tally,
            window_start=start,
            window_end=end,
            now=now or utc_now(),
            target_parts=target_parts,
            planned_duration_min=planned_duration_min,
        )

    def alerts(self, *, status: str | None = None, station_id: str | None = None) -> list[Alert]:
        query = "SELECT document FROM alerts WHERE 1=1"
        params = []
        if status:
            query += " AND status=?"
            params.append(status)
        if station_id:
            query += " AND station_id=?"
            params.append(station_id)
        query += " ORDER BY last_seen_at DESC, alert_id DESC"
        with self._lock:
            return [Alert.model_validate_json(row[0]) for row in self._conn.execute(query, params)]

    def events(self, *, station_id: str | None = None, limit: int = 100) -> list[EdgeEvent]:
        query = "SELECT document FROM events"
        params: list[str | int] = []
        if station_id:
            query += " WHERE station_id=?"
            params.append(station_id)
        query += " ORDER BY occurred_at DESC, event_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return [
                EdgeEvent.model_validate_json(row[0]) for row in self._conn.execute(query, params)
            ]

    def parts(self, *, station_id: str | None = None, limit: int = 100) -> list[Part]:
        query = "SELECT document FROM parts"
        params: list[str | int] = []
        if station_id:
            query += " WHERE station_id=?"
            params.append(station_id)
        query += " ORDER BY created_at DESC, part_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return [Part.model_validate_json(row[0]) for row in self._conn.execute(query, params)]

    def reports(self) -> list[OperatorReport]:
        with self._lock:
            return [
                OperatorReport.model_validate_json(row[0])
                for row in self._conn.execute("SELECT document FROM reports ORDER BY report_id")
            ]

    def model_status(self, station_id: str) -> list[dict]:
        with self._lock:
            return [
                json.loads(row[0])
                for row in self._conn.execute(
                    "SELECT document FROM models WHERE station_id=? ORDER BY use_case",
                    (station_id,),
                )
            ]
