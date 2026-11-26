"""Append one versioned Edge event inside an existing ProductionStore transaction."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime

from visionhub.integration.edge_events import EdgeEvent, EdgeEventType


def enqueue(
    conn: sqlite3.Connection,
    *,
    station_id: str,
    event_type: EdgeEventType,
    payload: object,
    occurred_at: datetime,
    simulated: bool,
    **headers: object,
) -> EdgeEvent:
    """The caller already owns BEGIN IMMEDIATE, so sequence allocation is serialized."""
    sequence = conn.execute(
        "SELECT COALESCE(MAX(edge_sequence), 0) + 1 FROM outbox WHERE station_id = ?",
        (station_id,),
    ).fetchone()[0]
    timestamp = (
        occurred_at.replace(tzinfo=UTC)
        if occurred_at.tzinfo is None
        else occurred_at.astimezone(UTC)
    )
    event = EdgeEvent(
        event_id=str(uuid.uuid4()),
        station_id=station_id,
        edge_sequence=sequence,
        event_type=event_type,
        occurred_at=timestamp,
        simulated=simulated,
        payload=payload,
        **headers,
    )
    conn.execute(
        "INSERT INTO outbox (event_id, station_id, edge_sequence, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            event.event_id,
            station_id,
            sequence,
            event.model_dump_json(),
            datetime.now(UTC).isoformat(),
        ),
    )
    return event
