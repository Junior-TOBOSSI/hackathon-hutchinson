"""DBX-08A retraining policies: versioning, conditions, statistics rigour, proposals,
guardrails, single launch path, automatic mode with a SIMULATED job provider."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mlops.databricks.connector import (
    ConflictError,
    DatabricksUnavailableError,
    ForbiddenOperationError,
)
from mlops.monitoring.store import MonitoringStore
from mlops.retraining import conditions as cond
from mlops.retraining.models import Condition, PolicyInput
from mlops.retraining.scheduler import Scheduler
from mlops.retraining.service import LaunchRefused, PolicyError, RetrainingService
from mlops.retraining.store import RetrainingStore

NOW = datetime(2026, 11, 27, 22, 0, tzinfo=UTC)


def item(sha, label="OK", split="train", review="validated"):
    return {
        "sha256": sha,
        "label": label,
        "split": split,
        "review": review,
        "file": f"{split}/{label}/{sha}.jpg",
    }


class FakeProviders:
    """Simulated platform: trainings, datasets, drift windows and a SIMULATED job provider."""

    def __init__(self) -> None:
        self.t = NOW
        self.remote = True
        self.spec_obj = SimpleNamespace(
            id="pipe",
            mlflow={"registered_model": "cat.q"},
            code={"commit": "abc"},
            dataset=SimpleNamespace(families=["fam"]),
            compute={"kind": "serverless-cpu", "gpu": False},
        )
        self.runs = [
            SimpleNamespace(
                job_run_id=1,
                pipeline_id="pipe",
                dataset_id="fam",
                dataset_version="v1",
                status="succeeded",
                started_at="2026-11-01T10:00:00+00:00",
            )
        ]
        self.vers = {"fam": ["v1", "v2"]}
        self.items = {
            ("fam", "v1"): [item(f"a{i}") for i in range(10)],
            ("fam", "v2"): [item(f"a{i}") for i in range(10)] + [item(f"n{i}") for i in range(5)],
        }
        self.windows: list[dict] | None = None
        self.launches: list[tuple] = []
        self.fail: Exception | None = None
        self.perf = None

    def now(self):
        return self.t

    def remote_enabled(self):
        return self.remote

    def spec(self, pipeline_id):
        if pipeline_id != "pipe":
            raise KeyError(pipeline_id)
        return self.spec_obj

    def managed(self, model_id):
        if model_id != "q":
            raise LookupError(model_id)
        return SimpleNamespace(uc_name="cat.q", argos_use_case="quality")

    def trainings(self):
        return self.runs

    def versions(self, family):
        return self.vers.get(family, [])

    def manifest_items(self, family, version):
        return self.items[(family, version)]

    def drift_windows(self, model_id):
        return self.windows

    def production_performance(self, model_id):
        return None

    def performance(self, model_id):
        return self.perf

    def launch(self, pipeline_id, family, version, key, source):
        if self.fail:
            raise self.fail
        self.launches.append((pipeline_id, family, version, key, source))
        return SimpleNamespace(job_run_id=100 + len(self.launches))


def policy(**kw) -> PolicyInput:
    base = {
        "name": "Qualité mensuelle",
        "use_case": "quality",
        "model_id": "q",
        "pipeline_id": "pipe",
        "dataset_family": "fam",
        "active": True,
        "mode": "manual",
        "logic": "OR",
        "conditions": [Condition(kind="annotations", enabled=True, annotations={"min_new": 3})],
        "guardrails": {"max_runs_per_month": 2, "min_hours_between": 0},
    }
    return PolicyInput(**{**base, **kw})


@pytest.fixture
def env(tmp_path):
    p = FakeProviders()
    return RetrainingService(p, RetrainingStore(tmp_path / "r.sqlite")), p


def window(day, level="alert", kind="real", status="available", representative=True):
    return {
        "window_day": day,
        "level": level,
        "data_kind": kind,
        "status": status,
        "representative": representative,
        "reference_id": "ref1",
        "model_version": "1",
    }


# --------------------------------------------------------------------------- policies


def test_every_change_is_a_new_version_and_history_is_kept(env):
    s, _ = env
    v1 = s.create(policy(active=False), "ai_leader")
    v2 = s.update(v1.policy_id, policy(active=False, logic="AND"), "ai_leader")
    v3 = s.set_active(v1.policy_id, True, "ai_leader")
    assert (v1.version, v2.version, v3.version) == (1, 2, 3) and v3.logic == "AND" and v3.active
    assert [p.version for p in s.store.history(v1.policy_id)] == [
        3,
        2,
        1,
    ] and v1.code_version == "abc"
    assert [e["event"] for e in s.store.audit(v1.policy_id)][::-1] == [
        "policy.created",
        "policy.updated",
        "policy.activated",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"pipeline_id": "other"},
        {"model_id": "x"},
        {"use_case": "safety"},
        {"dataset_family": "other"},
        {"dataset_selection": {"strategy": "pinned", "pinned_version": "v9"}},
    ],
)
def test_inconsistent_policies_are_refused(env, bad):
    s, _ = env
    with pytest.raises(PolicyError):
        s.create(policy(**bad), "ai_leader")


def test_a_policy_without_active_condition_never_triggers(env):
    s, p = env
    pol = s.create(policy(conditions=[Condition(kind="manual", enabled=False)]), "ai_leader")
    ev = s.evaluate(pol.policy_id)
    assert not ev.eligible and "no active condition" in ev.reason and s.store.proposals() == []


# --------------------------------------------------------------------------- conditions


def test_and_or_combination_and_required_unavailable_condition():
    sat = cond.ConditionResult(kind="manual", required=False, state="satisfied", reason="")
    una = cond.ConditionResult(kind="drift", required=False, state="unavailable", reason="")
    assert cond.combine("OR", [sat, una])[0] is True
    assert cond.combine("AND", [sat, una])[0] is False  # unavailable is never satisfied
    una_req = una.model_copy(update={"required": True})
    assert cond.combine("OR", [sat, una_req])[0] is False


def test_drift_requires_distinct_representative_windows_of_an_allowed_origin():
    c = Condition(kind="drift", enabled=True)
    assert cond.drift(c, None).state == "unavailable"  # no exact link with the registry
    assert cond.drift(c, [window("2026-11-25", representative=False)]).state == "unavailable"
    assert (
        cond.drift(c, [window("2026-11-25", status="insufficient_reference")]).state
        == "unavailable"
    )
    assert cond.drift(c, [window("2026-11-26")]).state == "not_satisfied"  # one window only
    assert (
        cond.drift(c, [window("2026-11-25"), window("2026-11-26", level="stable")]).state
        == "not_satisfied"
    )
    ok = cond.drift(c, [window("2026-11-25"), window("2026-11-26")])
    assert (
        ok.state == "satisfied"
        and ok.evidence_key == "drift:2026-11-25,2026-11-26"
        and not ok.simulated
    )
    assert (
        cond.drift(
            c, [window("2026-11-25", kind="simulated"), window("2026-11-26", kind="simulated")]
        ).state
        == "unavailable"
    )
    c_sim = Condition(kind="drift", enabled=True, drift={"allowed_origins": ["simulated"]})
    assert cond.drift(
        c_sim, [window("2026-11-25", kind="simulated"), window("2026-11-26", kind="simulated")]
    ).simulated


def test_several_collections_of_one_window_are_one_detection(tmp_path):
    m = MonitoringStore(tmp_path / "m.sqlite")
    for at in ("2026-11-26T10:00", "2026-11-26T11:00", "2026-11-26T12:00"):
        m.upsert_drift_window(
            "registry:q", "1", "real", "2026-11-26", at, {"status": "available", "level": "alert"}
        )
    rows = m.drift_windows("registry:q")
    assert len(rows) == 1 and rows[0]["computed_at"] == "2026-11-26T12:00"
    assert (
        cond.drift(
            Condition(kind="drift", enabled=True), [{**rows[0], "representative": True}]
        ).state
        == "not_satisfied"
    )


def test_annotation_diff_counts_only_new_or_modified_usable_training_annotations():
    trained = [item("a"), item("b"), item("c", split="test")]
    target = [
        item("a"),
        item("b", label="NOK", review="corrected"),
        item("c", label="NOK", split="test", review="corrected"),
        item("d"),
        item("d"),
        item("e", review=None),
        item("f", split="validation", review="imported"),
    ]
    d = cond.annotation_diff(trained, target)
    assert d == {
        "added": 2,
        "modified": 1,
        "new_usable": 3,
        "validated_without_change": 1,
        "test_split_changes": 1,
    }


def test_annotations_condition_uses_the_dataset_of_the_last_relevant_training(env):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    ev = s.evaluate(pol.policy_id)
    ann = ev.conditions[0]
    assert (
        ann.state == "satisfied"
        and ann.evidence["trained_on"] == "v1"
        and ann.evidence["new_usable"] == 5
    )
    p.runs = []
    assert s.evaluate(pol.policy_id).conditions[0].state == "unavailable"


def test_performance_stays_unavailable_without_ground_truth_and_schedule(env):
    s, p = env
    pol = s.create(
        policy(
            conditions=[
                Condition(kind="performance", enabled=True),
                Condition(kind="schedule", enabled=True, schedule={"interval_days": 20}),
            ]
        ),
        "ai_leader",
    )
    res = {r.kind: r for r in s.evaluate(pol.policy_id).conditions}
    assert res["performance"].state == "unavailable" and res["schedule"].state == "satisfied"
    p.t = datetime(2026, 11, 10, tzinfo=UTC)
    assert {r.kind: r for r in s.evaluate(pol.policy_id).conditions}[
        "schedule"
    ].state == "not_satisfied"


# --------------------------------------------------------------------------- proposals


def test_manual_mode_creates_one_proposal_per_evidence_and_never_launches(env):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    first = s.evaluate(pol.policy_id)
    again = s.evaluate(pol.policy_id)
    assert first.proposal_id and again.proposal_id is None and "no duplicate" in again.reason
    assert len(s.store.proposals()) == 1 and p.launches == []


def test_manual_request_is_consumed_by_one_proposal(env):
    s, _ = env
    pol = s.create(policy(conditions=[Condition(kind="manual", enabled=True)]), "ai_leader")
    assert not s.evaluate(pol.policy_id).eligible
    s.manual_request(pol.policy_id, "ai_leader", "nouveau lot")
    assert s.evaluate(pol.policy_id).proposal_id and s.store.pending_manual(pol.policy_id) == []
    assert not s.evaluate(pol.policy_id).eligible


def test_acceptance_launches_once_through_the_single_launch_path(env):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    pid = s.evaluate(pol.policy_id).proposal_id
    out = s.accept(pid, "ai_leader", "ok")
    assert out.status == "launched" and out.job_run_id == 101
    assert p.launches == [("pipe", "fam", "v2", f"policy-{pid}", f"policy:{pol.policy_id}@v1")]
    with pytest.raises(LaunchRefused, match="launched"):
        s.accept(pid, "ai_leader", None)
    assert len(p.launches) == 1


def test_rejection_is_journaled_and_final(env):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    pid = s.evaluate(pol.policy_id).proposal_id
    assert s.reject(pid, "ai_leader", "pas maintenant").status == "rejected"
    with pytest.raises(LaunchRefused):
        s.accept(pid, "ai_leader", None)
    assert p.launches == []


# --------------------------------------------------------------------------- guardrails


def refused(s, pid, match):
    with pytest.raises(LaunchRefused, match=match):
        s.accept(pid, "ai_leader", None)


def test_closed_lock_refuses_and_takes_no_reservation(env):
    s, p = env
    p.remote = False
    pol = s.create(policy(), "ai_leader")
    pid = s.evaluate(pol.policy_id).proposal_id
    refused(s, pid, "remote_lock")
    assert (
        s.store.ledger() == [] and p.launches == [] and s.store.proposal(pid).status == "accepted"
    )


@pytest.mark.parametrize(
    "setup,match",
    [
        (
            lambda p: p.runs.append(
                SimpleNamespace(
                    job_run_id=9,
                    pipeline_id="pipe",
                    dataset_id="fam",
                    dataset_version="v1",
                    status="running",
                    started_at="2026-11-27T21:00:00+00:00",
                )
            ),
            "no_concurrent_training",
        ),
        (lambda p: p.spec_obj.code.update(commit="def"), "code_version"),
        (lambda p: p.spec_obj.compute.update(gpu=True), "cpu_only"),
    ],
)
def test_static_guardrails_are_rechecked_at_launch(env, setup, match):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    pid = s.evaluate(pol.policy_id).proposal_id
    setup(p)
    refused(s, pid, match)
    assert p.launches == []


def test_allowed_hours_and_minimum_delay(env):
    s, p = env
    h = NOW.astimezone().hour
    pol = s.create(
        policy(guardrails={"allowed_hours": ((h + 1) % 24, (h + 2) % 24), "min_hours_between": 0}),
        "ai_leader",
    )
    refused(s, s.evaluate(pol.policy_id).proposal_id, "allowed_hours")
    pol2 = s.create(policy(guardrails={"min_hours_between": 24 * 60}), "ai_leader")
    refused(s, s.evaluate(pol2.policy_id).proposal_id, "minimum delay")


def test_budget_is_enforced_server_side_even_with_concurrent_acceptances(env):
    s, p = env
    pol = s.create(
        policy(guardrails={"max_runs_per_month": 1, "min_hours_between": 0}), "ai_leader"
    )
    pid = s.evaluate(pol.policy_id).proposal_id
    results = []

    def go():
        try:
            results.append(s.accept(pid, "ai_leader", None).status)
        except LaunchRefused as exc:
            results.append(str(exc))

    threads = [threading.Thread(target=go) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(p.launches) == 1 and results.count("launched") == 1
    s.manual_request(pol.policy_id, "ai_leader", None)
    pol = s.update(
        pol.policy_id,
        policy(
            guardrails={"max_runs_per_month": 1, "min_hours_between": 0},
            conditions=[Condition(kind="manual", enabled=True)],
        ),
        "ai_leader",
    )
    pid2 = s.evaluate(pol.policy_id).proposal_id
    refused(s, pid2, "monthly budget")
    assert len(p.launches) == 1


def test_policy_change_and_lost_conditions_are_rechecked_at_launch(env):
    s, p = env
    pol = s.create(policy(), "ai_leader")
    pid = s.evaluate(pol.policy_id).proposal_id
    s.update(pol.policy_id, policy(comment="seuil"), "ai_leader")
    refused(s, pid, "policy changed")
    pol2 = s.create(policy(name="autre"), "ai_leader")
    pid2 = s.evaluate(pol2.policy_id).proposal_id
    p.items[("fam", "v2")] = p.items[("fam", "v1")]
    refused(s, pid2, "conditions no longer met")


def test_simulated_evidence_never_launches_real_compute(env):
    s, p = env
    p.windows = [window("2026-11-25", kind="simulated"), window("2026-11-26", kind="simulated")]
    pol = s.create(
        policy(
            conditions=[
                Condition(kind="drift", enabled=True, drift={"allowed_origins": ["simulated"]})
            ]
        ),
        "ai_leader",
    )
    ev = s.evaluate(pol.policy_id)
    assert ev.eligible and s.store.proposal(ev.proposal_id).simulated
    refused(s, ev.proposal_id, "simulated")
    assert p.launches == []


def test_doubtful_answer_is_reconciled_with_the_same_key_and_counts_in_the_budget(env):
    s, p = env
    pol = s.create(
        policy(guardrails={"max_runs_per_month": 1, "min_hours_between": 0}), "ai_leader"
    )
    pid = s.evaluate(pol.policy_id).proposal_id
    p.fail = DatabricksUnavailableError("network")
    assert s.accept(pid, "ai_leader", None).status == "uncertain"
    assert s.store.ledger()[0]["status"] == "uncertain"
    p.fail = None
    out = s.reconcile(pid, "ai_leader")
    assert out.status == "launched" and p.launches[0][3] == f"policy-{pid}"


def test_training_service_refusal_releases_the_reservation(env):
    s, p = env
    pol = s.create(
        policy(guardrails={"max_runs_per_month": 1, "min_hours_between": 0}), "ai_leader"
    )
    pid = s.evaluate(pol.policy_id).proposal_id
    p.fail = ForbiddenOperationError("remote training launch is not authorized")
    refused(s, pid, "TrainingService refused")
    assert (
        s.store.ledger()[0]["status"] == "released" and s.store.proposal(pid).status == "accepted"
    )
    p.fail = ConflictError("blocking checks failed")
    refused(s, pid, "blocking checks")
    p.fail = None
    assert s.accept(pid, "ai_leader", None).status == "launched"  # budget was not consumed


# --------------------------------------------------------------------------- automatic mode


def test_automatic_mode_launches_only_when_everything_allows_it(env):
    s, p = env
    auto = s.create(policy(mode="auto"), "ai_leader")
    s.create(policy(name="manuelle"), "ai_leader")
    s.create(policy(name="inactive", mode="auto", active=False), "ai_leader")
    assert s.tick(False) == [] and p.launches == []  # scheduler disabled: nothing at all
    p.remote = False
    out = s.tick(True)
    assert p.launches == [] and any("remote_lock" in str(i.get("refused")) for i in out)
    p.remote = True
    out = s.tick(True)
    assert len(p.launches) == 1 and p.launches[0][4] == f"policy:{auto.policy_id}@v1"
    assert sum(1 for i in out if i.get("launched")) == 1  # the manual policy only proposes
    s.tick(True)
    assert len(p.launches) == 1  # same evidence: no new proposal, no second launch


def test_scheduler_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HOVIS_RETRAIN_SCHEDULER", raising=False)
    calls = []
    sch = Scheduler(lambda enabled: calls.append(enabled) or [])
    sch.start()
    assert sch.state()["enabled"] is False and sch.state()["running"] is False
    sch.run_once()
    assert calls == [False]


# --------------------------------------------------------------------------- comparison and routes


def perf_row(version, fp, recall, aliases=()):
    return {
        "version": version,
        "aliases": list(aliases),
        "dataset": {"test_fingerprint": fp},
        "metrics": {"recall_nok": recall, "accuracy": 0.9},
    }


def test_candidate_is_compared_with_the_champion_only_on_the_same_test_split(env):
    s, p = env
    p.perf = {
        "versions": [
            perf_row("2", "fp1", 0.8, ["champion"]),
            perf_row("5", "fp1", 0.9),
            perf_row("6", "fp2", 0.95),
        ]
    }
    same = s.comparison("q", "5")
    assert same["comparable"] and same["deltas"]["recall_nok"] == pytest.approx(0.1)
    other = s.comparison("q", "6")
    assert (
        not other["comparable"]
        and other["deltas"]["recall_nok"] is None
        and "NOT a reliable" in other["reason"]
    )


def test_routes_journal_and_refuse_launch_without_lock(env):
    s, p = env
    p.remote = False
    from mlops.api.retraining_routes import create_retraining_router

    conn = SimpleNamespace(settings=SimpleNamespace(request_budget_seconds=30, models=[]))
    app = FastAPI()
    app.include_router(
        create_retraining_router(lambda: conn, get_service=lambda c: s), prefix="/api"
    )
    api = TestClient(app)
    body = policy().model_dump(mode="json")
    pid = api.post("/api/mlops/retraining/policies", json=body).json()["policy_id"]
    assert (
        api.post("/api/mlops/retraining/policies", json={**body, "pipeline_id": "nope"}).status_code
        == 422
    )
    ev = api.post(f"/api/mlops/retraining/policies/{pid}/evaluate").json()
    assert ev["eligible"] and ev["proposal_id"]
    r = api.post(f"/api/mlops/retraining/proposals/{ev['proposal_id']}/accept", json={"note": "ok"})
    assert r.status_code == 409 and "remote_lock" in r.json()["detail"] and p.launches == []
    assert api.get("/api/mlops/retraining/scheduler").json()["enabled"] is False
    assert (
        api.get("/api/mlops/retraining/kpis").json()["pending_proposals"] == 0
    )  # accepted, not launched
    events = [e["event"] for e in api.get("/api/mlops/retraining/audit").json()]
    assert "launch.refused" in events and "proposal.accepted" in events
