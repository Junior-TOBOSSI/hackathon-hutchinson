"""Read-only sources of the monitoring. No second collection system, no copy of the Core.

- Core: its PUBLIC HTTP API only (``/api/v1/stations``, ``/events``, ``/parts``). The API
  returns at most 500 most recent items per call, without pagination nor time filter: when a
  station returns the maximum, the result is flagged ``truncated`` and every aggregation
  built on it is reported as PARTIAL, never as exhaustive.
- Deployment (Codex, DBX-06): optional; "unavailable" until its branch is integrated.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

CORE_LIMIT = 500


@dataclass
class SourceStatus:
    name: str
    status: str  # available | unavailable | partial
    fetched_at: str | None = None
    detail: str | None = None


@dataclass
class CoreSnapshot:
    stations: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    parts: list[dict] = field(default_factory=list)
    truncated_stations: list[str] = field(default_factory=list)
    status: SourceStatus = field(default_factory=lambda: SourceStatus("core", "unavailable"))


class CoreSource:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base = (base_url or os.environ.get("HOVIS_CORE_URL", "http://127.0.0.1:8020")).rstrip(
            "/"
        )
        self.timeout = timeout

    def _get(self, path: str) -> Any:
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read())

    def snapshot(self) -> CoreSnapshot:
        snap = CoreSnapshot()
        try:
            snap.stations = self._get("/api/v1/stations")
            for st in snap.stations:
                sid = st["station_id"]
                events = self._get(f"/api/v1/events?station_id={sid}&limit={CORE_LIMIT}")
                parts = self._get(f"/api/v1/parts?station_id={sid}&limit={CORE_LIMIT}")
                if len(events) >= CORE_LIMIT or len(parts) >= CORE_LIMIT:
                    snap.truncated_stations.append(sid)
                snap.events += events
                snap.parts += parts
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            snap.status = SourceStatus(
                "core", "unavailable", detail=f"{type(exc).__name__}: {str(exc)[:200]}"
            )
            return snap
        now = datetime.now(UTC).isoformat()
        partial = bool(snap.truncated_stations)
        snap.status = SourceStatus(
            "core",
            "partial" if partial else "available",
            now,
            f"API limited to {CORE_LIMIT} items per station: "
            f"truncated for {snap.truncated_stations}"
            if partial
            else None,
        )
        return snap


class DeploymentSource:
    """Desired versions per station from Codex's Deployment service, when integrated."""

    def desired(self) -> tuple[list[dict], SourceStatus]:
        try:
            from mlops.deployment import service as deployment  # noqa: F401 - Codex branch
        except ImportError:
            return [], SourceStatus(
                "deployment",
                "unavailable",
                detail="DBX-06 Deployment service not integrated in this branch",
            )
        return [], SourceStatus(
            "deployment",
            "unavailable",
            detail="Deployment service present: adapter to be wired at integration",
        )
