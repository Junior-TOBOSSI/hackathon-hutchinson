"""Bounded localhost HTTP delivery of durable ProductionStore outbox events."""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlsplit

import httpx

from visionhub.contracts import utc_now
from visionhub.integration.edge_events import EdgeEventBatch, IngestAck
from visionhub.production.store import ProductionStore

log = logging.getLogger(__name__)


def validate_core_url(url: str) -> str:
    """CORE-02 MVP only sends to a Core on this computer, never an external service."""
    parsed = urlsplit(url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ARGOS_CORE_URL must be a plain localhost HTTP origin")
    return url.rstrip("/")


class OutboxSender:
    def __init__(
        self, store: ProductionStore, core_url: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.store = store
        self.core_url = validate_core_url(core_url)
        self.transport = transport

    def send_once(self) -> bool | None:
        """True if sent, False on failure, None if nothing awaits delivery."""
        events = self.store.pending_events(limit=100)
        if not events:
            return None
        batch = EdgeEventBatch(station_id=events[0].station_id, sent_at=utc_now(), events=events)
        try:
            with httpx.Client(
                transport=self.transport, timeout=httpx.Timeout(5.0, connect=2.0)
            ) as client:
                response = client.post(
                    f"{self.core_url}/ingest/v1/events", json=batch.model_dump(mode="json")
                )
                response.raise_for_status()
                ack = IngestAck.model_validate(response.json())
            self.store.mark_ack(ack, events)
            return True
        except (httpx.HTTPError, ValueError) as exc:
            # A timeout may mean Core committed but its ACK was lost. Keep the exact
            # event_ids and replay; Core will return duplicate if it did commit.
            self.store.mark_failure(events, str(exc))
            log.warning("Core sync failed; %s event(s) retained: %s", len(events), exc)
            return False


class OutboxWorker:
    def __init__(self, sender: OutboxSender, *, interval_s: float = 0.5) -> None:
        self.sender = sender
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="argos-core-sync", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=6)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            try:
                result = self.sender.send_once()
            except Exception:
                # A storage failure must not terminate the Edge or lose its queue.
                log.exception("Core sync worker failed; will retry")
                result = False
            if result is True:
                failures = 0
                continue
            failures = min(failures + 1, 6) if result is False else 0
            delay = min(30.0, self.interval_s * (2**failures)) if failures else self.interval_s
            self._stop.wait(delay)
