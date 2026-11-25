"""Event storage in SQLite (a local file, or ":memory:"). No image is ever stored.

Each event is stored as JSON, with a few indexed columns used for filtering.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from visionhub.contracts import Decision, Event, OperatorFeedback, Stats, UseCase, UseCaseStats

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id  TEXT PRIMARY KEY,
    ts        TEXT NOT NULL,
    use_case  TEXT NOT NULL,
    decision  TEXT NOT NULL,
    feedback  INTEGER NOT NULL DEFAULT 0,
    payload   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_uc_dec ON events (use_case, decision);
"""


class EventStore:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the pipeline thread and the API, protected by a lock.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def add(self, event: Event) -> None:
        with self._lock, self._conn:
            self._conn.execute(
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

    def get(self, event_id: str) -> Event | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return Event.model_validate_json(row[0]) if row else None

    def list(
        self,
        use_case: UseCase | None = None,
        decision: Decision | None = None,
        pending_feedback: bool | None = None,
        limit: int = 50,
    ) -> list[Event]:
        """Most recent events first."""
        query, params = "SELECT payload FROM events WHERE 1=1", []
        if use_case is not None:
            query += " AND use_case = ?"
            params.append(use_case.value)
        if decision is not None:
            query += " AND decision = ?"
            params.append(decision.value)
        if pending_feedback is not None:
            query += " AND feedback = ?"
            params.append(0 if pending_feedback else 1)
        query += " ORDER BY ts DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [Event.model_validate_json(r[0]) for r in rows]

    def set_feedback(self, event_id: str, feedback: OperatorFeedback) -> Event | None:
        event = self.get(event_id)
        if event is None:
            return None
        event = event.model_copy(update={"operator_feedback": feedback})
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE events SET feedback = 1, payload = ? WHERE event_id = ?",
                (event.model_dump_json(), event_id),
            )
        return event

    def stats(self) -> Stats:
        with self._lock:
            rows = self._conn.execute(
                "SELECT use_case, decision, COUNT(*) FROM events GROUP BY use_case, decision"
            ).fetchall()
            pending = self._conn.execute(
                "SELECT use_case, COUNT(*) FROM events "
                "WHERE decision = ? AND feedback = 0 GROUP BY use_case",
                (Decision.A_VERIFIER.value,),
            ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for use_case, decision, n in rows:
            counts.setdefault(use_case, {})[decision] = n
        pending_by_uc = dict(pending)

        by_use_case = {}
        for use_case in sorted(set(counts) | set(pending_by_uc)):
            c = counts.get(use_case, {})
            by_use_case[use_case] = UseCaseStats(
                counts={d.value: c.get(d.value, 0) for d in Decision},
                pending_review=pending_by_uc.get(use_case, 0),
            )
        return Stats(by_use_case=by_use_case)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
