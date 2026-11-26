"""Reuse of MLflow's Databricks host credentials (DBX-PERF-01).

Problem measured: for EVERY request, MLflow's Databricks REST stores call
``mlflow.utils.databricks_utils.get_databricks_host_creds``. With the SDK auth path, that
function builds a new ``databricks.sdk.WorkspaceClient`` only to discover the host: one
``/.well-known/databricks-config`` request plus one Databricks CLI process (OAuth profile
``auth_type=databricks-cli``), i.e. ~2.3 s per MLflow call, cached or not.

What is cached here: the ``MlflowHostCreds`` object returned by that function. On the SDK
path it carries the host, the profile name and the workspace id, but NO token
(``use_databricks_sdk=True``, ``token=None``). The token itself lives in the
``WorkspaceClient`` that MLflow keeps in ``rest_utils.get_workspace_client`` (lru_cache);
that client renews the OAuth token by itself when it expires, so nothing here can freeze an
expired token.

Safety rules:
- only token-less SDK credentials are cached; credentials carrying a token (legacy or
  secret-scope paths) are returned as is, every time;
- a cache belongs to ONE store of ONE client (store URI bound by MLflow): no mixing of
  profiles or workspaces; the host of the cached value must stay the same;
- a failure is never cached (the next call retries the normal MLflow path);
- nothing about the credentials is logged.

Dependency on MLflow internals (checked with mlflow 3.18): ``MlflowClient._tracking_client
.store.get_host_creds`` and ``MlflowClient._get_registry_client().store.get_host_creds`` /
``.get_tracking_host_creds``. MLflow offers no public way to do this. If those attributes
are missing (other MLflow version), nothing is installed and MLflow keeps its default
behaviour (slower, still correct).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 600
TESTED_MLFLOW = "3.18"


class CachedHostCreds:
    """Callable replacing a store's ``get_host_creds``; caches token-less SDK credentials."""

    def __init__(self, fetch: Callable[[], Any], ttl: float = DEFAULT_TTL_SECONDS, clock=time):
        self._fetch = fetch
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._fetching = threading.Lock()
        self._value: Any = None
        self._at = 0.0

    @staticmethod
    def cacheable(creds: Any) -> bool:
        return bool(getattr(creds, "use_databricks_sdk", False)) and not getattr(
            creds, "token", None
        )

    def _fresh_value(self) -> Any:
        with self._lock:
            if self._value is not None and self._clock.time() - self._at < self._ttl:
                return self._value
        return None

    def __call__(self) -> Any:
        cached = self._fresh_value()
        if cached is not None:
            return cached
        # One resolution at a time: concurrent first requests wait for it instead of each
        # launching its own Databricks CLI process.
        with self._fetching:
            cached = self._fresh_value()
            if cached is not None:
                return cached
            creds = self._fetch()  # exceptions propagate: never cached
        if not self.cacheable(creds):
            return creds
        with self._lock:
            if self._value is not None and getattr(self._value, "host", None) != getattr(
                creds, "host", None
            ):
                log.warning("Databricks host changed for an MLflow store; cache reset")
            self._value, self._at = creds, self._clock.time()
        return creds

    def clear(self) -> None:
        with self._lock:
            self._value = None


def _wrap(store: Any, attribute: str, ttl: float) -> bool:
    current = getattr(store, attribute, None)
    if current is None or not callable(current):
        return False
    if isinstance(current, CachedHostCreds):
        return True
    setattr(store, attribute, CachedHostCreds(current, ttl))
    return True


def install_host_creds_cache(client: Any, ttl: float = DEFAULT_TTL_SECONDS) -> bool:
    """Install the cache on an ``MlflowClient`` for Databricks. Returns False (and changes
    nothing) when the MLflow internals are not the expected ones."""
    try:
        tracking_store = client._tracking_client.store
        registry_store = client._get_registry_client().store
    except Exception:  # noqa: BLE001 - other MLflow version: keep the default behaviour
        log.warning("MLflow host credentials cache not installed (unexpected MLflow internals)")
        return False
    ok = _wrap(tracking_store, "get_host_creds", ttl)
    ok = _wrap(registry_store, "get_host_creds", ttl) and ok
    _wrap(registry_store, "get_tracking_host_creds", ttl)  # UC registry only (optional)
    if not ok:
        log.warning("MLflow host credentials cache only partially installed")
    return ok
