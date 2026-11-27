"""DBX-09 home page aggregation: independent blocks, exact definitions, real dated activity,
read-only. Fakes only (no Databricks, no Core process)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.overview import service as ov

T = datetime(2026, 11, 27, 8, tzinfo=UTC)


def model(mid, uc="quality", endpoint="ep"):
    return NS(
        id=mid,
        display_name=f"Model {mid}",
        argos_use_case=uc,
        uc_name=f"cat.sch.{mid}",
        synthetic=True,
        endpoint=endpoint,
    )


def vs(v, approved=False, aliases=(), served_by=()):
    return NS(
        version=NS(version=v, created_at=T.replace(hour=int(v))),
        approved=approved,
        aliases=list(aliases),
        served_by=list(served_by),
    )


class Conn:
    def __init__(self):
        self.settings = NS(
            models=[model("q"), model("s", "safety", None)],
            catalog="workspace",
            request_budget_seconds=30,
        )
        self.status = {
            "q": NS(
                aliases={"champion": "2", "challenger": "1"},
                served={"ep": "2"},
                versions=[
                    vs("1", aliases=["challenger"]),
                    vs("2", True, ["champion"], ["ep"]),
                    vs("3"),
                    vs("4"),
                ],
            ),
            "s": NS(aliases={}, served={}, versions=[vs("1")]),
        }
        self.fail_registry = False

    def _cached(self, key, loader, ttl=None):
        return loader()

    def model_status(self, mid):
        if self.fail_registry and mid == "s":
            raise RuntimeError("UC unreachable")
        return self.status[mid]

    def ping(self):
        return NS(model_dump=lambda: {"ok": True})

    def list_experiments(self):
        return [1, 2]

    def list_catalogs(self):
        return ["workspace"]

    def list_endpoints(self):
        return [NS(name="ep", ready="READY", served=[NS(model="cat.sch.q", version="2")])]


class Store:
    def __init__(self):
        self.calls = 0

    def catalog(self):
        return [
            NS(
                dataset_id="d1",
                name="D1",
                use_case="quality",
                synthetic=True,
                version_count=2,
                latest_version="v2",
                latest_images=100,
                last_published_at=None,
                draft_count=1,
            ),
            NS(
                dataset_id="d2",
                name="D2",
                use_case="safety",
                synthetic=False,
                version_count=1,
                latest_version="v1",
                latest_images=None,
                last_published_at=None,
                draft_count=0,
            ),
        ]

    def family_index(self, fid):
        return NS(
            versions=[
                NS(
                    version="v1",
                    created_at="2026-11-26T10:00:00Z",
                    classes=["OK", "NOK"],
                    counts={"train": {"OK": 3, "NOK": 2}, "test": {"OK": 1, "NOK": 1}},
                )
            ]
        )


class Decisions:
    def decisions(self, mid, v):
        if (mid, v) == ("q", "4"):
            return [
                NS(
                    decision="rejected",
                    status="applied",
                    created_at="2026-11-27T09:00:00Z",
                    reason="bad",
                )
            ]
        return []

    def list(self, endpoint, limit):
        return [
            NS(
                created_at="2026-11-27T10:00:00Z",
                kind="rollback",
                endpoint="ep",
                version="1",
                reason="incident",
                status="succeeded",
            )
        ]


class Monitoring:
    def __init__(self):
        self.store = NS(alerts=lambda state=None: [])
        self.writes = 0

    def _snapshot(self):
        return NS(
            stations=[
                {
                    "station_id": "S1",
                    "simulated": True,
                    "online": True,
                    "cell": "C",
                    "models": [{"use_case": "quality", "model_name": "demo", "model_version": "1"}],
                },
                {"station_id": "S2", "simulated": True, "online": False, "cell": "C", "models": []},
            ],
            status=NS(status="available", detail=None, fetched_at="2026-11-27T10:00:00Z"),
        )

    def summary(self, kind):
        return {
            "status": "available",
            "sources": [],
            "inferences": 0 if kind == "real" else 50,
            "latency_p95": 19.0,
            "open_alerts": 0,
            "drift_alerts": 0,
            "availability_alerts": 0,
            "last_collection": None,
        }

    def models(self, kind):
        return [
            {
                "source": "operational",
                "drift": {"status": "reference_absent"},
                "needs_investigation": False,
            },
            {
                "source": "operational",
                "drift": {"status": "insufficient_reference"},
                "needs_investigation": False,
            },
            {
                "source": "registry",
                "drift": {"status": "no_production_data"},
                "needs_investigation": False,
            },
        ]


class Training:
    def trainings(self):
        return [
            NS(
                job_run_id=7,
                pipeline_id="p",
                dataset_id="d1",
                dataset_version="v1",
                status="succeeded",
                started_at="2026-11-27T07:00:00+00:00",
                ended_at="2026-11-27T07:30:00+00:00",
                duration_s=1800,
                model_versions=["3"],
                model_dump=lambda: {"status": "succeeded"},
            ),
            NS(
                job_run_id=8,
                pipeline_id="p",
                dataset_id="d1",
                dataset_version="v1",
                status="running",
                started_at="2026-11-27T11:00:00+00:00",
                ended_at=None,
                duration_s=None,
                model_versions=[],
                model_dump=lambda: {"status": "running"},
            ),
        ]

    def kpis(self):
        return NS(model_dump=lambda: {"candidates": 2})

    def pipelines(self):
        return [NS(spec=NS(id="p", name="P", use_case="quality"), executable=True)]


@pytest.fixture
def env(monkeypatch):
    c, mon = Conn(), Monitoring()
    monkeypatch.setattr(ov, "_store", lambda c: Store())
    monkeypatch.setattr(ov, "_training", lambda c: Training())
    monkeypatch.setattr(ov, "_monitoring", lambda c: mon)
    monkeypatch.setattr(ov, "_decisions", lambda: Decisions())
    return c, mon


def test_datasets_distinguish_families_versions_and_images(env):
    c, _ = env
    b = ov.build(c, "datasets")
    d = b["data"]
    assert b["status"] == "available" and d["families"] == 2 and d["published_versions"] == 3
    assert d["latest_images"] is None  # one family has an unknown image count: no false total
    assert d["by_use_case"] == {"quality": 1, "safety": 1}


def test_registry_never_mixes_candidates_approvals_champions_serving_and_edge(env):
    c, _ = env
    q = next(m for m in ov.build(c, "registry")["data"]["models"] if m["model_id"] == "q")
    assert q["candidates"] == 1  # v3 only: v1 has an alias, v2 approved, v4 rejected
    assert q["approved"] == 1 and q["champion"] == "2" and q["served"] == {"ep": "2"}
    assert q["edge_declared"] == [
        {
            "station_id": "S1",
            "simulated": True,
            "use_case": "quality",
            "model_name": "demo",
            "model_version": "1",
        }
    ]


def test_a_failing_source_makes_its_block_partial_not_the_page(env):
    c, _ = env
    c.fail_registry = True
    b = ov.build(c, "registry")
    assert b["status"] == "partial" and b["failed"][0]["source"] == "registry s"
    assert [m["model_id"] for m in b["data"]["models"]] == ["q"]


def test_a_failing_block_is_unavailable_and_others_still_answer(env, monkeypatch):
    c, _ = env
    monkeypatch.setitem(ov.BUILDERS, "datasets", lambda c, p: 1 / 0)
    from mlops.api.overview_routes import create_overview_router

    app = FastAPI()
    app.include_router(create_overview_router(lambda: c), prefix="/api")
    api = TestClient(app)
    blocks = {b["name"]: b for b in api.get("/api/mlops/overview/v2").json()["blocks"]}
    assert set(blocks) == set(ov.BLOCKS)
    assert (
        blocks["datasets"]["status"] == "unavailable"
        and "ZeroDivisionError" in blocks["datasets"]["detail"]
    )
    assert blocks["registry"]["status"] == "available"
    assert api.get("/api/mlops/overview/v2/registry").json()["name"] == "registry"
    assert api.get("/api/mlops/overview/v2/nope").status_code == 404
    assert [
        b["name"]
        for b in api.get("/api/mlops/overview/v2?blocks=training,monitoring").json()["blocks"]
    ] == ["training", "monitoring"]


def test_training_counts_real_runs_by_status(env):
    c, _ = env
    d = ov.build(c, "training")["data"]
    assert (
        d["by_status"] == {"succeeded": 1, "running": 1}
        and d["running"] == 1
        and len(d["runs"]) == 2
    )


def test_monitoring_is_flagged_simulated_and_coverage_is_not_stability(env):
    c, _ = env
    b = ov.build(c, "monitoring")
    d = b["data"]
    assert b["status"] == "simulated" and d["data_kind"] == "simulated" and d["inferences"] == 50
    assert (
        d["drift_detected"] == 0 and d["insufficient_coverage"] == 2 and d["reference_absent"] == 1
    )
    assert "not a proof of stability" in d["note"]


def test_infrastructure_reports_each_check_and_the_fleet(env):
    c, _ = env
    d = ov.build(c, "infrastructure")["data"]
    assert {x["name"]: x["status"] for x in d["checks"]} == {
        "databricks": "available",
        "mlflow": "available",
        "unity_catalog": "available",
    }
    assert d["fleet"] == {"stations": 2, "online": 1, "offline": 1, "simulated": 2, "cells": 1}
    assert d["monitoring_coverage"]["registry_models_without_inference"] == 1


def test_activity_is_real_dated_sorted_and_linked(env, monkeypatch, tmp_path):
    c, _ = env
    from mlops.api import retraining_routes

    monkeypatch.setattr(
        retraining_routes, "retraining_for", lambda c: NS(store=NS(proposals=lambda: []))
    )
    d = ov.build(c, "activity")["data"]
    ats = [e["at"] for e in d["events"]]
    assert ats == sorted(ats, reverse=True) and all(e["source"] for e in d["events"])
    types = {e["type"] for e in d["events"]}
    assert {
        "dataset",
        "training_started",
        "training_ended",
        "model_version",
        "decision",
        "rollback",
    } <= types
    run = next(e for e in d["events"] if e["type"] == "training_ended")
    assert run["link"] == {"section": "training", "run": "7"} and run["status"] == "succeeded"
    started = [e for e in d["events"] if e["type"] == "training_started"]
    assert {e["status"] for e in started} == {"started", "running"}  # start != final outcome
    assert next(e for e in d["events"] if e["type"] == "dataset")["detail"].startswith("7 images")
    assert d["not_dated"]  # alias promotions are explicitly not dated


def test_retraining_block_is_read_only(env, monkeypatch, tmp_path):
    c, _ = env
    from mlops.api import retraining_routes
    from mlops.retraining.store import RetrainingStore

    store = RetrainingStore(tmp_path / "r.sqlite")
    monkeypatch.setattr(retraining_routes, "retraining_for", lambda c: NS(store=store))
    monkeypatch.delenv("HOVIS_TRAINING_REMOTE", raising=False)
    d = ov.build(c, "retraining")["data"]
    assert (
        d["active"] == 0
        and d["pending_proposals"] == 0
        and d["remote_lock"]["remote_launch_enabled"] is False
    )
    assert store.evaluations() == [] and store.audit() == []  # nothing evaluated or written
