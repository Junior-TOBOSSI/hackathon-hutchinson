"""Retraining engine: versioned policies, evaluation, proposals, guardrails, launch.

The ONLY launch path is ``providers.launch`` = TrainingService.launch (authorization lock,
pipeline / dataset / compatibility checks, persistent idempotency, journal). Budgets and
delays are enforced inside a SQLite write transaction (see RetrainingStore.reserve), so
concurrent evaluations or double clicks cannot exceed them nor launch a proposal twice.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from mlops.retraining import conditions as cond
from mlops.retraining.models import (
    ConditionResult,
    Evaluation,
    GuardResult,
    PolicyInput,
    Proposal,
    RetrainPolicyConfig,
)
from mlops.retraining.store import RetrainingStore


class LaunchRefused(Exception):
    """A proposal could not be launched (reason kept on the proposal and in the audit)."""


class PolicyError(ValueError):
    pass


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- providers


class Providers:
    """Real sources (Training Factory, dataset catalogue, monitoring history). Tests inject
    fakes with the same methods: no Databricks call is ever needed to test the engine."""

    def __init__(self, connector) -> None:
        self.c = connector

    @property
    def training(self):
        from mlops.api.training_routes import service_for

        return service_for(self.c)

    def now(self) -> datetime:
        return datetime.now(UTC)

    def remote_enabled(self) -> bool:
        from mlops.training.service import remote_enabled

        return remote_enabled()

    def spec(self, pipeline_id: str):
        return self.training.spec(pipeline_id)

    def managed(self, model_id: str):
        return self.c.managed(model_id)

    def trainings(self) -> list[Any]:
        return self.training.trainings()

    def versions(self, family: str) -> list[str]:
        idx = self.training.resolver.store.family_index(family)
        return [v.version for v in sorted(idx.versions, key=lambda v: v.created_at or "")]

    def manifest_items(self, family: str, version: str) -> list[dict]:
        return self.training.resolver.manifest(family, version)[1].get("items", [])

    def drift_windows(self, model_id: str) -> list[dict] | None:
        from mlops.monitoring.store import MonitoringStore

        rows = MonitoringStore().drift_windows(f"registry:{model_id}")
        return rows or None  # no row = no inference linked to this registered model

    def production_performance(self, model_id: str) -> dict | None:
        return None  # no representative labelled production sample exists yet

    def performance(self, model_id: str) -> dict:
        from mlops.api.monitoring_routes import monitoring_for

        return monitoring_for(self.c).performance(model_id)

    def launch(self, pipeline_id: str, family: str, version: str, key: str, source: str):
        return self.training.launch(pipeline_id, family, version, {}, key, source=source)


# --------------------------------------------------------------------------- service


class RetrainingService:
    def __init__(self, providers: Providers, store: RetrainingStore | None = None) -> None:
        self.p = providers
        self.store = store or RetrainingStore()

    # ------------------------------------------------------------------ policies

    def _check(self, data: PolicyInput) -> str:
        """Consistency of a policy with the platform; returns the scientific code version."""
        try:
            spec = self.p.spec(data.pipeline_id)
        except Exception as exc:  # noqa: BLE001 - unknown pipeline
            raise PolicyError(f"unknown pipeline {data.pipeline_id!r}") from exc
        try:
            managed = self.p.managed(data.model_id)
        except Exception as exc:  # noqa: BLE001 - unknown model
            raise PolicyError(f"unknown model {data.model_id!r}") from exc
        if spec.mlflow.get("registered_model") != managed.uc_name:
            raise PolicyError(f"pipeline {spec.id} does not register into {managed.uc_name}")
        if data.use_case != managed.argos_use_case:
            raise PolicyError(f"model {data.model_id} belongs to use case {managed.argos_use_case}")
        if data.dataset_family not in spec.dataset.families:
            raise PolicyError(
                f"dataset family {data.dataset_family} is not declared by pipeline {spec.id}"
            )
        sel = data.dataset_selection
        if sel.strategy == "pinned" and sel.pinned_version not in self.p.versions(
            data.dataset_family
        ):
            raise PolicyError(
                f"version {sel.pinned_version} is not published in {data.dataset_family}"
            )
        return spec.code.get("commit") or "unknown"

    def create(self, data: PolicyInput, author: str) -> RetrainPolicyConfig:
        return self._save(uuid.uuid4().hex[:12], data, author, "policy.created")

    def update(self, policy_id: str, data: PolicyInput, author: str) -> RetrainPolicyConfig:
        if not self.store.policy(policy_id):
            raise LookupError(f"unknown policy {policy_id}")
        return self._save(policy_id, data, author, "policy.updated")

    def set_active(self, policy_id: str, active: bool, author: str) -> RetrainPolicyConfig:
        cur = self._policy(policy_id)
        data = PolicyInput(
            **{**cur.model_dump(include=set(PolicyInput.model_fields)), "active": active}
        )
        return self._save(
            policy_id, data, author, "policy.activated" if active else "policy.deactivated"
        )

    def _save(
        self, policy_id: str, data: PolicyInput, author: str, event: str
    ) -> RetrainPolicyConfig:
        code = self._check(data)
        now = iso(self.p.now())
        pol = RetrainPolicyConfig(
            **data.model_dump(),
            policy_id=policy_id,
            version=self.store.next_version(policy_id),
            code_version=code,
            created_at=now,
            author=author,
        )
        self.store.add_policy(pol)  # insert-only: every change is a new version
        self.store.log(
            now, author, event, policy_id, version=pol.version, active=pol.active, mode=pol.mode
        )
        return pol

    def _policy(self, policy_id: str) -> RetrainPolicyConfig:
        pol = self.store.policy(policy_id)
        if pol is None:
            raise LookupError(f"unknown policy {policy_id}")
        return pol

    def manual_request(self, policy_id: str, actor: str, note: str | None) -> str:
        self._policy(policy_id)
        now = iso(self.p.now())
        rid = self.store.add_manual_request(policy_id, now, actor, note)
        self.store.log(now, actor, "manual.requested", policy_id, request_id=rid, note=note)
        return rid

    # ------------------------------------------------------------------ evaluation

    def _last_training(self, pol: RetrainPolicyConfig) -> dict | None:
        rows = [
            r
            for r in self.p.trainings()
            if r.pipeline_id == pol.pipeline_id
            and r.dataset_id == pol.dataset_family
            and r.status == "succeeded"
            and r.started_at
        ]
        if not rows:
            return None
        r = max(rows, key=lambda x: x.started_at)
        return {
            "job_run_id": r.job_run_id,
            "dataset_version": r.dataset_version,
            "started_at": r.started_at,
        }

    def _target_version(self, pol: RetrainPolicyConfig) -> str | None:
        if pol.dataset_selection.strategy == "pinned":
            return pol.dataset_selection.pinned_version
        versions = self.p.versions(pol.dataset_family)
        return versions[-1] if versions else None

    def _conditions(
        self,
        pol: RetrainPolicyConfig,
        last: dict | None,
        target: str | None,
        proposal_id: str | None = None,
    ) -> list[ConditionResult]:
        out = []
        for c in (x for x in pol.conditions if x.enabled):
            if c.kind == "drift":
                out.append(cond.drift(c, self.p.drift_windows(pol.model_id)))
            elif c.kind == "annotations":
                trained = last.get("dataset_version") if last else None
                diff = None
                if trained and target:
                    diff = (
                        cond.annotation_diff([], [])
                        if trained == target
                        else cond.annotation_diff(
                            self.p.manifest_items(pol.dataset_family, trained),
                            self.p.manifest_items(pol.dataset_family, target),
                        )
                    )
                out.append(cond.annotations(c, trained, target, diff))
            elif c.kind == "performance":
                out.append(cond.performance(c, self.p.production_performance(pol.model_id)))
            elif c.kind == "schedule":
                out.append(cond.schedule(c, last, self.p.now()))
            else:
                # at launch, the requests consumed by THIS proposal still justify it
                own = self.store.consumed_manual(proposal_id) if proposal_id else []
                out.append(cond.manual(c, own + self.store.pending_manual(pol.policy_id)))
        return out

    def guards(
        self, pol: RetrainPolicyConfig, last: dict | None, simulated: bool
    ) -> list[GuardResult]:
        """Informative at evaluation, re-checked at launch (budget / delay: in the reservation)."""
        now = self.p.now()
        spec = self.p.spec(pol.pipeline_id)
        g = [
            GuardResult(
                name="remote_lock",
                ok=self.p.remote_enabled(),
                detail="HOVIS_TRAINING_REMOTE=1"
                if self.p.remote_enabled()
                else "remote launches not authorized",
            )
        ]
        hours = pol.guardrails.allowed_hours
        h = now.astimezone().hour
        in_window = hours is None or (
            hours[0] <= h < hours[1] if hours[0] < hours[1] else h >= hours[0] or h < hours[1]
        )
        g.append(
            GuardResult(
                name="allowed_hours",
                ok=in_window,
                detail="any hour" if hours is None else f"{hours[0]}h-{hours[1]}h, now {h}h",
            )
        )
        gpu = "gpu" in json.dumps(spec.compute, default=str).lower()
        g.append(
            GuardResult(
                name="cpu_only",
                ok=not gpu,
                detail="CPU compute" if not gpu else "pipeline requests a GPU",
            )
        )
        busy = [
            r.job_run_id
            for r in self.p.trainings()
            if r.pipeline_id == pol.pipeline_id and r.status in ("queued", "running")
        ]
        g.append(
            GuardResult(
                name="no_concurrent_training",
                ok=not busy,
                detail=f"active runs {busy}" if busy else "none active",
            )
        )
        code = spec.code.get("commit") or "unknown"
        g.append(
            GuardResult(
                name="code_version",
                ok=code == pol.code_version,
                detail=f"policy {pol.code_version[:12]} / pipeline {code[:12]}",
            )
        )
        g.append(
            GuardResult(
                name="real_data_only",
                ok=not simulated,
                detail="simulated evidence never triggers real remote compute"
                if simulated
                else "real evidence",
            )
        )
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        launched = [
            x
            for x in self.store.ledger(pol.policy_id)
            if x["status"] in ("reserved", "launched", "uncertain")
        ]
        n = sum(1 for x in launched if x["at"] >= iso(month))
        g.append(
            GuardResult(
                name="monthly_budget",
                ok=n < pol.guardrails.max_runs_per_month,
                detail=f"{n} / {pol.guardrails.max_runs_per_month} this month",
            )
        )
        last_at = max(
            [x["at"] for x in launched]
            + (
                [iso(datetime.fromisoformat(last["started_at"].replace("Z", "+00:00")))]
                if last
                else []
            ),
            default=None,
        )
        wait_ok = last_at is None or now - datetime.fromisoformat(last_at) >= timedelta(
            hours=pol.guardrails.min_hours_between
        )
        g.append(
            GuardResult(
                name="min_delay",
                ok=wait_ok,
                detail=f"last training {last_at or 'none'}, "
                f"minimum {pol.guardrails.min_hours_between} h",
            )
        )
        return g

    def evaluate(
        self,
        policy_id: str,
        trigger: str = "explicit",
        actor: str = "ai_leader",
        proposal_id: str | None = None,
    ) -> Evaluation:
        pol = self._policy(policy_id)
        last = self._last_training(pol)
        target = self._target_version(pol)
        results = self._conditions(pol, last, target, proposal_id)
        eligible, reason = cond.combine(pol.logic, results)
        if eligible and target is None:
            eligible, reason = False, "no published dataset version to train on"
        simulated = any(r.simulated for r in results if r.state == "satisfied")
        ev = Evaluation(
            evaluation_id=uuid.uuid4().hex,
            policy_id=pol.policy_id,
            policy_version=pol.version,
            at=iso(self.p.now()),
            trigger=trigger,
            logic=pol.logic,
            conditions=results,
            eligible=eligible,
            reason=reason,
            target_dataset_version=target,
            guards=self.guards(pol, last, simulated),
        )
        if trigger == "launch_check":
            return ev
        if eligible and not pol.active:
            ev.reason += " (inactive policy: no proposal)"
        elif eligible:
            prop = self._propose(pol, ev, results, target, simulated)
            ev.proposal_id = prop.proposal_id if prop else None
            if prop is None:
                ev.reason += " (same evidence already proposed: no duplicate)"
        self.store.add_evaluation(ev)
        self.store.log(
            ev.at,
            actor,
            "policy.evaluated",
            pol.policy_id,
            trigger=trigger,
            eligible=ev.eligible,
            reason=ev.reason,
            proposal_id=ev.proposal_id,
        )
        return ev

    def _propose(self, pol, ev, results, target, simulated) -> Proposal | None:
        sat = sorted(r.evidence_key for r in results if r.state == "satisfied" and r.evidence_key)
        key = hashlib.sha256(json.dumps([pol.pipeline_id, target, sat]).encode()).hexdigest()[:24]
        manual_ids = next(
            (
                r.evidence.get("requests", [])
                for r in results
                if r.kind == "manual" and r.state == "satisfied"
            ),
            [],
        )
        prop = Proposal(
            proposal_id=uuid.uuid4().hex[:16],
            policy_id=pol.policy_id,
            policy_version=pol.version,
            evidence_key=key,
            status="pending",
            created_at=ev.at,
            updated_at=ev.at,
            mode=pol.mode,
            model_id=pol.model_id,
            pipeline_id=pol.pipeline_id,
            dataset_family=pol.dataset_family,
            dataset_version=target,
            reasons=[r.reason for r in results if r.state == "satisfied"],
            conditions=results,
            simulated=simulated,
        )
        created = self.store.create_proposal(prop, manual_ids)
        if created:
            self.store.log(
                ev.at,
                "engine",
                "proposal.created",
                pol.policy_id,
                proposal_id=prop.proposal_id,
                dataset_version=target,
                simulated=simulated,
            )
        return created

    # ------------------------------------------------------------------ decisions and launch

    def reject(self, proposal_id: str, actor: str, note: str | None) -> Proposal:
        p = self._proposal(proposal_id)
        if p.status not in ("pending", "accepted"):
            raise LaunchRefused(f"proposal is {p.status}: it cannot be rejected")
        p.status, p.decided_by, p.decision_note, p.updated_at = (
            "rejected",
            actor,
            note,
            iso(self.p.now()),
        )
        self.store.save_proposal(p)
        self.store.log(
            p.updated_at,
            actor,
            "proposal.rejected",
            p.policy_id,
            proposal_id=proposal_id,
            note=note,
        )
        return p

    def accept(self, proposal_id: str, actor: str, note: str | None) -> Proposal:
        p = self._proposal(proposal_id)
        if p.status == "pending":
            p.status, p.decided_by, p.decision_note, p.updated_at = (
                "accepted",
                actor,
                note,
                iso(self.p.now()),
            )
            self.store.save_proposal(p)
            self.store.log(
                p.updated_at,
                actor,
                "proposal.accepted",
                p.policy_id,
                proposal_id=proposal_id,
                note=note,
            )
        return self.launch(proposal_id, actor)

    def _proposal(self, proposal_id: str) -> Proposal:
        p = self.store.proposal(proposal_id)
        if p is None:
            raise LookupError(f"unknown proposal {proposal_id}")
        return p

    def _refuse(self, p: Proposal, actor: str, reason: str) -> None:
        cur = self.store.proposal(p.proposal_id) or p
        cur.last_error, cur.updated_at = reason, iso(self.p.now())
        self.store.save_proposal(cur)
        self.store.log(
            cur.updated_at,
            actor,
            "launch.refused",
            p.policy_id,
            proposal_id=p.proposal_id,
            reason=reason,
        )
        raise LaunchRefused(reason)

    def launch(self, proposal_id: str, actor: str) -> Proposal:
        """Re-checks EVERYTHING at launch time, reserves atomically, then TrainingService.launch."""
        p = self._proposal(proposal_id)
        if p.status not in ("pending", "accepted"):
            self._refuse(p, actor, f"proposal is {p.status}: it cannot be launched (again)")
        pol = self._policy(p.policy_id)
        if pol.version != p.policy_version:
            self._refuse(
                p,
                actor,
                f"policy changed since the proposal (v{p.policy_version} -> v{pol.version}): "
                "re-evaluate",
            )
        if not pol.active:
            self._refuse(p, actor, "policy is inactive")
        ev = self.evaluate(pol.policy_id, "launch_check", actor, proposal_id=p.proposal_id)
        if not ev.eligible:
            self._refuse(p, actor, f"conditions no longer met: {ev.reason}")
        if p.simulated:
            self._refuse(p, actor, "simulated evidence never triggers real remote compute")
        static = [
            g for g in ev.guards if not g.ok and g.name not in ("monthly_budget", "min_delay")
        ]
        if static:
            self._refuse(
                p, actor, "guardrails: " + "; ".join(f"{g.name} ({g.detail})" for g in static)
            )
        last = self._last_training(pol)
        now = self.p.now()

        def ledger_check(c, prop) -> str | None:  # inside the write transaction
            month = iso(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
            if (
                self.store.counted_since(c, pol.policy_id, month)
                >= pol.guardrails.max_runs_per_month
            ):
                return f"monthly budget reached ({pol.guardrails.max_runs_per_month})"
            prev = [
                x
                for x in (
                    self.store.last_launch(c, pol.policy_id),
                    iso(datetime.fromisoformat(last["started_at"].replace("Z", "+00:00")))
                    if last
                    else None,
                )
                if x
            ]
            if prev and now - datetime.fromisoformat(max(prev)) < timedelta(
                hours=pol.guardrails.min_hours_between
            ):
                h = pol.guardrails.min_hours_between
                return f"minimum delay of {h} h not elapsed since {max(prev)}"
            return None

        reserved, reason = self.store.reserve(proposal_id, ledger_check, iso(now))
        if reason:
            self._refuse(p, actor, reason)
        self.store.log(
            iso(now),
            actor,
            "launch.reserved",
            pol.policy_id,
            proposal_id=proposal_id,
            idempotency_key=reserved.idempotency_key,
        )
        return self._submit(reserved, pol, actor, previous_status=p.status)

    def _submit(
        self, p: Proposal, pol: RetrainPolicyConfig, actor: str, previous_status: str
    ) -> Proposal:
        from mlops.databricks.connector import DatabricksConnectorError, DatabricksUnavailableError

        try:
            rec = self.p.launch(
                p.pipeline_id,
                p.dataset_family,
                p.dataset_version,
                p.idempotency_key,
                source=f"policy:{pol.policy_id}@v{pol.version}",
            )
        except DatabricksUnavailableError as exc:  # doubtful answer: keep the key, reconcile later
            self.store.settle(p.proposal_id, "uncertain")
            p.status, p.last_error, p.updated_at = "uncertain", str(exc)[:300], iso(self.p.now())
            self.store.save_proposal(p)
            self.store.log(
                p.updated_at, actor, "launch.uncertain", p.policy_id, proposal_id=p.proposal_id
            )
            return p
        except (DatabricksConnectorError, ValueError) as exc:  # refused: release the reservation
            self.store.settle(p.proposal_id, "released")
            p.status = previous_status
            self.store.save_proposal(p)
            self._refuse(p, actor, f"TrainingService refused: {exc}")
        self.store.settle(p.proposal_id, "launched", rec.job_run_id)
        p.status, p.job_run_id, p.last_error, p.updated_at = (
            "launched",
            rec.job_run_id,
            None,
            iso(self.p.now()),
        )
        self.store.save_proposal(p)
        self.store.log(
            p.updated_at,
            actor,
            "launch.submitted",
            p.policy_id,
            proposal_id=p.proposal_id,
            job_run_id=rec.job_run_id,
            note="new model version stays a candidate (no alias, no approval)",
        )
        return p

    def reconcile(self, proposal_id: str, actor: str) -> Proposal:
        """After a doubtful answer: retry with the SAME idempotency key (Databricks dedupes)."""
        p = self._proposal(proposal_id)
        if p.status != "uncertain":
            raise LaunchRefused(f"proposal is {p.status}: nothing to reconcile")
        return self._submit(p, self._policy(p.policy_id), actor, previous_status="uncertain")

    # ------------------------------------------------------------------ scheduler tick

    def tick(self, scheduler_enabled: bool) -> list[dict[str, Any]]:
        """One scheduler pass. Launches ONLY for active automatic policies, when the scheduler
        is explicitly enabled; TrainingService.launch still requires the remote lock."""
        if not scheduler_enabled:
            return []
        out = []
        for pol in self.store.policies():
            if not pol.active:
                continue
            ev = self.evaluate(pol.policy_id, trigger="scheduler", actor="scheduler")
            item = {
                "policy_id": pol.policy_id,
                "eligible": ev.eligible,
                "proposal_id": ev.proposal_id,
            }
            pending = [x for x in self.store.proposals(pol.policy_id) if x.status == "pending"]
            if pol.mode == "auto":
                for prop in pending:
                    try:
                        item["launched"] = self.launch(prop.proposal_id, "scheduler").job_run_id
                    except LaunchRefused as exc:
                        item["refused"] = str(exc)
            out.append(item)
        return out

    # ------------------------------------------------------------------ comparison and KPIs

    def comparison(self, model_id: str, version: str) -> dict[str, Any]:
        """Candidate vs champion, ONLY presented as an improvement measure when both were
        evaluated on the same test split (identical fingerprint of images + labels)."""
        perf = self.p.performance(model_id)
        rows = {r["version"]: r for r in perf["versions"]}
        champ = next((r for r in perf["versions"] if "champion" in r["aliases"]), None)
        cand = rows.get(version)
        if cand is None or champ is None:
            return {"comparable": False, "reason": "candidate or champion version not found"}
        fc, fh = cand["dataset"]["test_fingerprint"], champ["dataset"]["test_fingerprint"]
        comparable = bool(fc and fc == fh)
        deltas = {
            k: (cand["metrics"].get(k) - champ["metrics"][k])
            if comparable
            and cand["metrics"].get(k) is not None
            and champ["metrics"].get(k) is not None
            else None
            for k in champ["metrics"]
        }
        return {
            "comparable": comparable,
            "candidate": cand,
            "champion": champ,
            "deltas": deltas,
            "reason": "same test split (identical fingerprint)"
            if comparable
            else "different or unknown test splits / annotations: "
            "NOT a reliable measure of improvement",
            "note": "offline evaluation only; approval and deployment stay human decisions",
        }

    def kpis(self, scheduler: dict[str, Any]) -> dict[str, Any]:
        pols = self.store.policies()
        props = self.store.proposals()
        month = iso(self.p.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        return {
            "policies": len(pols),
            "active": sum(p.active for p in pols),
            "auto": sum(p.active and p.mode == "auto" for p in pols),
            "pending_proposals": sum(p.status == "pending" for p in props),
            "uncertain_proposals": sum(p.status == "uncertain" for p in props),
            "launched_this_month": sum(
                1 for x in self.store.ledger() if x["status"] == "launched" and x["at"] >= month
            ),
            "scheduler": scheduler,
            "remote_launch_enabled": self.p.remote_enabled(),
        }
