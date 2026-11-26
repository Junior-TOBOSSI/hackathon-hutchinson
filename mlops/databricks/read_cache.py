"""In-memory read cache of the Databricks connector (DBX-PERF-01). No external service.

- TTL per key (60 s for current state, 1 h for finished MLflow runs);
- single-flight: concurrent requests for the same key share ONE remote read;
- generations: ``invalidate`` (or a forced fresh read) bumps the key's generation, so a
  remote read started BEFORE a mutation can never write its result back into the cache;
- a remote error never replaces the last valid value; when Databricks is unreachable the
  last valid value may be served, explicitly marked ``stale``;
- ``fetched_at`` is the moment the REMOTE read completed, never the moment it was served.

A ``read_scope`` (one per API request) carries the ``fresh`` flag, the request time budget
and the list of reads, from which the freshness headers are computed.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

STALE_MAX_SECONDS = 24 * 3600


class BudgetExceeded(Exception):
    """The request spent its whole time budget (several remote calls in a row)."""


@dataclass
class ReadScope:
    fresh: bool = False
    deadline: float | None = None
    reads: list[tuple[datetime, str]] = field(default_factory=list)

    def remaining(self) -> float | None:
        return None if self.deadline is None else self.deadline - time.monotonic()

    def check_budget(self) -> None:
        left = self.remaining()
        if left is not None and left <= 0:
            raise BudgetExceeded("request time budget exceeded")

    def headers(self) -> dict[str, str]:
        """``X-HOVIS-Fetched-At`` = OLDEST remote read used by the response (conservative);
        ``X-HOVIS-Cache`` = miss (all read now) | hit (all from cache) | mixed | stale."""
        if not self.reads:
            return {}
        kinds = {kind for _, kind in self.reads}
        kind = "stale" if "stale" in kinds else kinds.pop() if len(kinds) == 1 else "mixed"
        oldest = min(at for at, _ in self.reads)
        return {"X-HOVIS-Fetched-At": oldest.isoformat(), "X-HOVIS-Cache": kind}


_SCOPE: contextvars.ContextVar[ReadScope | None] = contextvars.ContextVar(
    "hovis_read_scope", default=None
)


def current_scope() -> ReadScope | None:
    return _SCOPE.get()


@contextmanager
def read_scope(fresh: bool = False, budget: float | None = None) -> Iterator[ReadScope]:
    scope = ReadScope(fresh=fresh, deadline=None if budget is None else time.monotonic() + budget)
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


@contextmanager
def fresh_reads() -> Iterator[None]:
    """Force real remote reads inside the block (used after a mutation)."""
    scope = _SCOPE.get()
    if scope is None:
        with read_scope(fresh=True):
            yield
        return
    previous, scope.fresh = scope.fresh, True
    try:
        yield
    finally:
        scope.fresh = previous


@dataclass
class _Entry:
    value: Any
    fetched_at: datetime
    stored: float
    ttl: float


@dataclass
class _Flight:
    generation: int
    done: threading.Event = field(default_factory=threading.Event)
    value: Any = None
    fetched_at: datetime | None = None
    kind: str = "miss"
    error: BaseException | None = None


class ReadCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._generations: dict[str, int] = {}
        self._flights: dict[str, _Flight] = {}

    # ------------------------------------------------------------------ reads

    def get(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: float | Callable[[Any], float],
        stale_on: tuple[type[BaseException], ...] = (),
    ) -> Any:
        scope = _SCOPE.get()
        fresh = bool(scope and scope.fresh)
        with self._lock:
            entry = self._entries.get(key)
            if not fresh and entry and self._clock() - entry.stored < entry.ttl:
                self._record(scope, entry.fetched_at, "hit")
                return entry.value
            if fresh:
                # A forced read must not join (nor be overwritten by) an older read.
                self._bump(key)
            flight = self._flights.get(key)
            leader = flight is None or flight.generation != self._generations.get(key, 0)
            if leader:
                flight = _Flight(generation=self._generations.get(key, 0))
                self._flights[key] = flight
        if not leader:
            return self._wait(flight, scope)
        try:
            value = loader()
        except BaseException as exc:
            stale = self._stale(key) if stale_on and isinstance(exc, stale_on) else None
            with self._lock:
                if self._flights.get(key) is flight:
                    del self._flights[key]
            if stale is None:
                flight.error = exc
                flight.done.set()
                raise
            flight.value, flight.fetched_at, flight.kind = stale.value, stale.fetched_at, "stale"
            flight.done.set()
            self._record(scope, stale.fetched_at, "stale")
            return stale.value
        fetched_at = datetime.now(UTC)
        with self._lock:
            if self._generations.get(key, 0) == flight.generation:
                seconds = ttl(value) if callable(ttl) else ttl
                self._entries[key] = _Entry(value, fetched_at, self._clock(), seconds)
            if self._flights.get(key) is flight:
                del self._flights[key]
        flight.value, flight.fetched_at = value, fetched_at
        flight.done.set()
        self._record(scope, fetched_at, "miss")
        return value

    def _wait(self, flight: _Flight, scope: ReadScope | None) -> Any:
        left = scope.remaining() if scope else None
        if not flight.done.wait(timeout=None if left is None else max(left, 0)):
            raise BudgetExceeded("request time budget exceeded while waiting for a shared read")
        if flight.error is not None:
            raise flight.error
        self._record(scope, flight.fetched_at, flight.kind)
        return flight.value

    def _stale(self, key: str) -> _Entry | None:
        with self._lock:
            entry = self._entries.get(key)
        if entry and self._clock() - entry.stored < STALE_MAX_SECONDS:
            return entry
        return None

    @staticmethod
    def _record(scope: ReadScope | None, fetched_at: datetime | None, kind: str) -> None:
        if scope is not None and fetched_at is not None:
            scope.reads.append((fetched_at, kind))

    # ------------------------------------------------------------------ invalidation

    def _bump(self, key: str) -> None:
        self._generations[key] = self._generations.get(key, 0) + 1

    def invalidate(self, *prefixes: str) -> None:
        """Drop matching entries; reads already running for them will not be stored."""
        with self._lock:
            keys = {k for k in (*self._entries, *self._flights, *self._generations)}
            for key in keys:
                if any(key.startswith(p) for p in prefixes):
                    self._bump(key)
                    self._entries.pop(key, None)

    @contextmanager
    def mutation(self, *prefixes: str) -> Iterator[None]:
        """Invalidate before AND after a remote write: a read started during the write
        (thus possibly seeing the old state) cannot repopulate the cache."""
        self.invalidate(*prefixes)
        try:
            yield
        finally:
            self.invalidate(*prefixes)

    def clear(self) -> None:
        self.invalidate("")
