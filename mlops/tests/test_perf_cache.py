"""DBX-PERF-01: MLflow credentials reuse, read cache, freshness headers, budgets.

No Databricks call: fakes and mocks only (real credentials are never touched).
"""

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.api import routes
from mlops.databricks.auth_cache import CachedHostCreds, install_host_creds_cache
from mlops.databricks.connector import DatabricksUnavailableError
from mlops.databricks.read_cache import BudgetExceeded, ReadCache, fresh_reads, read_scope
from mlops.tests.test_databricks_unit import connector  # noqa: F401 - shared fixture


class Clock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def __call__(self):
        return self.now


def sdk_creds(host="https://a.cloud.databricks.com"):
    return SimpleNamespace(host=host, token=None, use_databricks_sdk=True)


# ------------------------------------------------------------------ MLflow credentials


def test_token_less_sdk_creds_are_reused_then_renewed():
    clock, calls = Clock(), []
    cached = CachedHostCreds(lambda: calls.append(1) or sdk_creds(), ttl=600, clock=clock)
    assert cached() is cached()
    assert len(calls) == 1
    clock.now += 601  # TTL elapsed: MLflow's normal path runs again (renewal)
    cached()
    assert len(calls) == 2


def test_creds_carrying_a_token_are_never_cached():
    calls = []
    legacy = SimpleNamespace(host="h", token="secret-value", use_databricks_sdk=False)
    cached = CachedHostCreds(lambda: calls.append(1) or legacy)
    cached(), cached()
    assert len(calls) == 2


def test_auth_failure_is_not_cached_and_nothing_sensitive_is_logged(caplog):
    attempts = []

    def fetch():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("cannot configure default credentials")
        return sdk_creds()

    cached = CachedHostCreds(fetch)
    with pytest.raises(RuntimeError):
        cached()
    assert cached().host.startswith("https://")
    assert len(attempts) == 2
    caplog.set_level(logging.DEBUG)
    install_host_creds_cache(object())  # unexpected internals: warning only
    assert "token" not in caplog.text.lower() and "secret" not in caplog.text.lower()


def test_one_cache_per_store_no_profile_mixing():
    a = CachedHostCreds(lambda: sdk_creds("https://a"))
    b = CachedHostCreds(lambda: sdk_creds("https://b"))
    assert a().host == "https://a" and b().host == "https://b"


def test_install_is_idempotent_and_has_a_fallback():
    def store():
        return SimpleNamespace(get_host_creds=sdk_creds, get_tracking_host_creds=sdk_creds)

    tracking, registry = store(), store()
    client = SimpleNamespace(
        _tracking_client=SimpleNamespace(store=tracking),
        _get_registry_client=lambda: SimpleNamespace(store=registry),
    )
    assert install_host_creds_cache(client) and install_host_creds_cache(client)
    assert isinstance(tracking.get_host_creds, CachedHostCreds)
    assert isinstance(registry.get_tracking_host_creds, CachedHostCreds)
    assert not isinstance(tracking.get_host_creds._fetch, CachedHostCreds)
    assert install_host_creds_cache(object()) is False


def test_compatible_with_the_installed_mlflow(monkeypatch):
    """Builds a real MlflowClient for Databricks (no network) and checks the internals."""
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "hovis-test-no-such-profile")
    from mlflow import MlflowClient

    client = MlflowClient(tracking_uri="databricks", registry_uri="databricks-uc")
    assert install_host_creds_cache(client)
    assert isinstance(client._tracking_client.store.get_host_creds, CachedHostCreds)
    assert isinstance(client._get_registry_client().store.get_host_creds, CachedHostCreds)


# ------------------------------------------------------------------ read cache


def test_ttl_hit_then_miss_and_fetched_at_is_the_remote_read():
    clock, calls = Clock(), []
    cache = ReadCache(clock=clock)
    with read_scope() as first:
        cache.get("k", lambda: calls.append(1) or "v1", ttl=60)
    clock.now += 30
    with read_scope() as second:
        assert cache.get("k", lambda: "never", ttl=60) == "v1"
    assert second.headers()["X-HOVIS-Cache"] == "hit"
    assert second.headers()["X-HOVIS-Fetched-At"] == first.headers()["X-HOVIS-Fetched-At"]
    clock.now += 31  # expired
    with read_scope() as third:
        assert cache.get("k", lambda: "v2", ttl=60) == "v2"
    assert third.headers()["X-HOVIS-Cache"] == "miss" and len(calls) == 1


def test_concurrent_requests_share_one_remote_read():
    cache, calls, gate = ReadCache(), [], threading.Event()

    def slow():
        calls.append(1)
        gate.wait(2)
        return "v"

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(cache.get("k", slow, 60))) for _ in range(10)
    ]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(3)
    assert results == ["v"] * 10 and len(calls) == 1


def test_fresh_bypasses_the_cache():
    cache = ReadCache()
    cache.get("k", lambda: "old", 60)
    with read_scope(fresh=True) as scope:
        assert cache.get("k", lambda: "new", 60) == "new"
    assert scope.headers()["X-HOVIS-Cache"] == "miss"
    assert cache.get("k", lambda: "never", 60) == "new"


def test_read_started_before_a_mutation_cannot_repopulate_the_cache():
    cache, started, release = ReadCache(), threading.Event(), threading.Event()

    def old_state():
        started.set()
        release.wait(2)
        return "before-mutation"

    reader = threading.Thread(target=lambda: cache.get("versions:q", old_state, 60))
    reader.start()
    started.wait(2)
    with cache.mutation("versions:q"):
        pass  # the remote write happens here
    release.set()
    reader.join(3)
    assert cache.get("versions:q", lambda: "after-mutation", 60) == "after-mutation"


def test_error_never_replaces_the_last_valid_value():
    clock = Clock()
    cache = ReadCache(clock=clock)
    cache.get("k", lambda: "valid", 60)
    clock.now += 61

    def down():
        raise DatabricksUnavailableError("Databricks unreachable")

    with pytest.raises(DatabricksUnavailableError):  # not allowed to serve stale
        cache.get("k", down, 60)
    with read_scope() as scope:
        assert cache.get("k", down, 60, stale_on=(DatabricksUnavailableError,)) == "valid"
    assert scope.headers()["X-HOVIS-Cache"] == "stale"


def test_errors_are_not_cached():
    cache, calls = ReadCache(), []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        cache.get("k", flaky, 60)
    assert cache.get("k", flaky, 60) == "ok"


def test_budget_bounds_the_whole_request_and_the_wait():
    with read_scope(budget=0) as scope, pytest.raises(BudgetExceeded):
        scope.check_budget()
    cache, gate = ReadCache(), threading.Event()
    leader = threading.Thread(target=lambda: cache.get("k", lambda: gate.wait(2) and "v", 60))
    leader.start()
    time.sleep(0.1)
    with read_scope(budget=0.2), pytest.raises(BudgetExceeded):
        cache.get("k", lambda: "never", 60)
    gate.set()
    leader.join(3)


def test_fresh_reads_inside_a_cached_scope():
    cache = ReadCache()
    cache.get("k", lambda: "old", 60)
    with read_scope() as scope:
        with fresh_reads():
            assert cache.get("k", lambda: "new", 60) == "new"
        assert scope.fresh is False


# ------------------------------------------------------------------ connector + API


@pytest.fixture
def api(connector):  # noqa: F811
    app = FastAPI()
    app.include_router(routes.create_mlops_router(lambda: connector), prefix="/api")
    return TestClient(app)


def test_status_is_cached_with_headers_and_fresh_rereads(api, connector):  # noqa: F811
    first = api.get("/api/mlops/models/q/status")
    assert first.status_code == 200 and first.headers["X-HOVIS-Cache"] == "miss"
    second = api.get("/api/mlops/models/q/status")
    assert second.headers["X-HOVIS-Cache"] == "hit"
    assert second.headers["X-HOVIS-Fetched-At"] == first.headers["X-HOVIS-Fetched-At"]
    assert connector.mlflow.get_registered_model.call_count == 1
    forced = api.get("/api/mlops/models/q/status?fresh=true")
    assert forced.headers["X-HOVIS-Cache"] == "miss"
    assert connector.mlflow.get_registered_model.call_count == 2


def test_overview_reuses_the_status_and_runs(api, connector):  # noqa: F811
    api.get("/api/mlops/models/q/status")
    calls = connector.mlflow.get_registered_model.call_count
    overview = api.get("/api/models/overview")
    assert overview.status_code == 200
    assert connector.mlflow.get_registered_model.call_count == calls
    run_ids = [c.args[0] for c in connector.mlflow.get_run.call_args_list]
    assert len(run_ids) == len(set(run_ids))  # each run read once


def test_approval_invalidates_and_returns_the_real_state(api, connector):  # noqa: F811
    api.get("/api/mlops/models/q/status")  # cached: v1 not approved
    tags: dict[str, dict] = {"2": {"argos_approval": "approved"}, "1": {}}
    original = connector.mlflow.get_model_version.side_effect

    def get_version(name, n):
        v = original(name, n)
        v.tags = tags[str(n)]
        return v

    connector.mlflow.get_model_version.side_effect = get_version
    connector.mlflow.set_model_version_tag.side_effect = lambda name, n, k, val: tags[n].update(
        {k: val}
    )
    approved = api.post("/api/mlops/models/q/versions/1/approve")
    assert approved.status_code == 200 and approved.json()["approved"] is True
    status = api.get("/api/mlops/models/q/status").json()
    assert {v["version"]["version"]: v["approved"] for v in status["versions"]}["1"] is True


def test_alias_change_is_visible_immediately(api, connector):  # noqa: F811
    api.get("/api/mlops/models/q/status")
    connector.mlflow.get_registered_model.return_value = SimpleNamespace(
        aliases={"champion": "1", "challenger": "2"}
    )
    moved = api.post("/api/models/q/promote", json={"version": "1"}).json()
    assert moved["aliases"]["champion"] == "1"
    assert api.get("/api/mlops/models/q/status").json()["aliases"]["champion"] == "1"


def test_databricks_down_serves_last_known_value_marked_stale(api, connector):  # noqa: F811
    clock = Clock()
    connector.reads = ReadCache(clock=clock)
    connector.w.serving_endpoints.list.return_value = [SimpleNamespace(name="ep")]
    assert api.get("/api/mlops/endpoints").status_code == 200
    clock.now += 61
    connector.w.serving_endpoints.list.side_effect = ConnectionError("Connection refused")
    stale = api.get("/api/mlops/endpoints")
    assert stale.status_code == 200 and stale.headers["X-HOVIS-Cache"] == "stale"


def test_unreachable_without_previous_value_is_a_fast_503(api, connector):  # noqa: F811
    connector.w.serving_endpoints.list.side_effect = ConnectionError("Connection refused")
    assert api.get("/api/mlops/endpoints").status_code == 503


def test_exhausted_budget_is_a_503(api, connector, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        connector,
        "settings",
        connector.settings.__class__(models=connector.settings.models, request_budget_seconds=0),
    )
    assert api.get("/api/mlops/models/q/status").status_code == 503


def test_warm_up_never_raises(monkeypatch):
    from mlops.api import platform

    def broken():
        raise RuntimeError("Databricks unreachable")

    monkeypatch.setattr(platform, "default_connector", broken)
    platform.warm_up()  # logged, not raised
    thread = platform.start_warm_up()
    thread.join(5)
    assert not thread.is_alive()


def test_real_sdk_client_gets_bounded_timeouts(tmp_path, monkeypatch):
    """Builds a REAL WorkspaceClient from a throw-away local profile (no network)."""
    from mlops.databricks.connector import build_workspace_client
    from mlops.databricks.settings import DatabricksSettings

    cfg = tmp_path / "databrickscfg"
    cfg.write_text("[hovis-test]\nhost = https://example.cloud.databricks.com\ntoken = x\n")
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(cfg))
    for var in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_AUTH_TYPE"):
        monkeypatch.delenv(var, raising=False)
    client = build_workspace_client(DatabricksSettings(profile="hovis-test"))
    assert client.config.http_timeout_seconds == 15
    assert client.config.retry_timeout_seconds == 30


def test_concurrent_first_requests_resolve_credentials_once():
    calls, gate = [], threading.Event()

    def slow_fetch():
        calls.append(1)
        gate.wait(2)
        return sdk_creds()

    cached = CachedHostCreds(slow_fetch)
    threads = [threading.Thread(target=cached) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(3)
    assert len(calls) == 1
