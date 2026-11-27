"""Process-wide counters of REMOTE work, for performance audits (INT-GLOBAL-01).

Enabled with ``HOVIS_PERF_COUNTERS=1`` (read-only diagnostics, no behaviour change):
- every outgoing HTTP request made through ``requests`` (MLflow client and Databricks SDK),
  grouped by host and API family (``/api/2.0/mlflow``, ``/api/2.1/unity-catalog``...), with
  cumulated time;
- every ``databricks`` CLI process started (authentication resolution of the SDK / MLflow).

``GET /api/mlops/_perf`` returns a snapshot; callers diff two snapshots around an action.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

_LOCK = threading.Lock()
_HTTP: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
_CLI: dict[str, int] = defaultdict(int)
_INSTALLED = False
_FAMILY = re.compile(r"^(/api/[0-9.]+/[a-z-]+)")


def _family(url: str) -> str:
    u = urlparse(url)
    m = _FAMILY.match(u.path or "")
    return f"{u.hostname}{m.group(1) if m else (u.path or '/')[:40]}"


def install() -> bool:
    global _INSTALLED
    if _INSTALLED or os.environ.get("HOVIS_PERF_COUNTERS") != "1":
        return _INSTALLED
    import requests

    original = requests.Session.request

    def counted(self, method, url, *args, **kwargs):  # noqa: ANN001
        start = time.perf_counter()
        try:
            return original(self, method, url, *args, **kwargs)
        finally:
            key = f"{method} {_family(str(url))}"
            with _LOCK:
                _HTTP[key][0] += 1
                _HTTP[key][1] += time.perf_counter() - start

    requests.Session.request = counted

    popen_init = subprocess.Popen.__init__

    def counted_popen(self, args, *a, **kw):  # noqa: ANN001
        text = " ".join(args) if isinstance(args, list | tuple) else str(args)
        if "databricks" in os.path.basename(text.split(" ")[0]).lower():
            with _LOCK:
                _CLI[" ".join(text.split(" ")[1:3])] += 1
        return popen_init(self, args, *a, **kw)

    subprocess.Popen.__init__ = counted_popen
    _INSTALLED = True
    return True


def snapshot() -> dict[str, Any]:
    with _LOCK:
        http = {k: {"calls": v[0], "seconds": round(v[1], 3)} for k, v in sorted(_HTTP.items())}
        cli = dict(_CLI)
    return {
        "enabled": _INSTALLED,
        "http_calls": sum(v["calls"] for v in http.values()),
        "http": http,
        "cli_calls": sum(cli.values()),
        "cli": cli,
    }
