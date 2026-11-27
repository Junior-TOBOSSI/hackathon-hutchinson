"""DBX-08 retraining policy routes (``/api/mlops/retraining/...``), included by the MLOps router.

Writes are local (SQLite) except proposal acceptance, which launches ONLY through
TrainingService.launch (authorization lock, checks, idempotency, journal). Reads that touch
Databricks use the DBX-PERF-01 request scope.
"""

import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from mlops.databricks.connector import DatabricksConnector, DatabricksConnectorError
from mlops.databricks.read_cache import BudgetExceeded, read_scope
from mlops.retraining.models import Evaluation, PolicyInput, Proposal, RetrainPolicyConfig
from mlops.retraining.scheduler import Scheduler
from mlops.retraining.service import LaunchRefused, PolicyError, Providers, RetrainingService

_LOCK = threading.Lock()
SCHEDULER = None  # set by create_retraining_router (state shown on the home page)
ACTOR = "ai_leader"  # no user identity in the local gateway: actions are journaled with this role


def retraining_for(c: DatabricksConnector) -> RetrainingService:
    svc = getattr(c, "_retraining_service", None)
    if svc is None:
        with _LOCK:
            svc = getattr(c, "_retraining_service", None)
            if svc is None:
                svc = RetrainingService(Providers(c))
                c._retraining_service = svc
    return svc


class NoteBody(BaseModel):
    note: str | None = Field(None, max_length=500)


def create_retraining_router(
    get_connector: Callable[[], DatabricksConnector],
    get_service: Callable[[DatabricksConnector], RetrainingService] = retraining_for,
) -> APIRouter:
    router = APIRouter(prefix="/mlops/retraining", tags=["retraining"])
    Connector = Annotated[DatabricksConnector, Depends(get_connector)]
    scheduler = Scheduler(lambda enabled: get_service(get_connector()).tick(enabled))
    scheduler.start()  # no-op unless HOVIS_RETRAIN_SCHEDULER=1
    global SCHEDULER
    SCHEDULER = scheduler  # read-only state for the AI Leader home page

    def call(c: DatabricksConnector, response: Response | None, fn: Callable[[], Any]) -> Any:
        try:
            with read_scope(fresh=False, budget=c.settings.request_budget_seconds) as scope:
                result = fn()
            if response is not None:
                response.headers.update(scope.headers())
            return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (PolicyError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except LaunchRefused as exc:
            raise HTTPException(409, str(exc)) from exc
        except DatabricksConnectorError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(503, f"Databricks too slow: {exc}") from exc

    @router.get("/kpis")
    def kpis(c: Connector) -> dict[str, Any]:
        return call(c, None, lambda: get_service(c).kpis(scheduler.state()))

    @router.get("/scheduler")
    def scheduler_state() -> dict[str, Any]:
        return scheduler.state()

    @router.get("/options")
    def options(c: Connector) -> list[dict[str, Any]]:
        """Models with the pipelines registering into them (code version, dataset families)."""

        def load() -> list[dict[str, Any]]:
            specs = get_service(c).p.training.specs
            return [
                {
                    "model_id": m.id,
                    "name": m.display_name,
                    "use_case": m.argos_use_case,
                    "uc_name": m.uc_name,
                    "pipelines": [
                        {
                            "pipeline_id": s.id,
                            "name": s.name,
                            "code_version": s.code.get("commit"),
                            "families": s.dataset.families,
                        }
                        for s in specs
                        if s.mlflow.get("registered_model") == m.uc_name
                    ],
                }
                for m in c.settings.models
            ]

        return call(c, None, load)

    @router.get("/policies")
    def policies(c: Connector) -> list[RetrainPolicyConfig]:
        return get_service(c).store.policies()

    @router.get("/policies/{policy_id}")
    def policy(policy_id: str, c: Connector) -> dict[str, Any]:
        s = get_service(c)
        history = s.store.history(policy_id)
        if not history:
            raise HTTPException(404, f"unknown policy {policy_id}")
        return {
            "current": history[0],
            "history": history,
            "manual_requests": s.store.pending_manual(policy_id),
        }

    @router.post("/policies", status_code=201)
    def create(body: PolicyInput, c: Connector) -> RetrainPolicyConfig:
        return call(c, None, lambda: get_service(c).create(body, ACTOR))

    @router.put("/policies/{policy_id}")
    def update(policy_id: str, body: PolicyInput, c: Connector) -> RetrainPolicyConfig:
        return call(c, None, lambda: get_service(c).update(policy_id, body, ACTOR))

    @router.post("/policies/{policy_id}/activate")
    def activate(policy_id: str, c: Connector) -> RetrainPolicyConfig:
        return call(c, None, lambda: get_service(c).set_active(policy_id, True, ACTOR))

    @router.post("/policies/{policy_id}/deactivate")
    def deactivate(policy_id: str, c: Connector) -> RetrainPolicyConfig:
        return call(c, None, lambda: get_service(c).set_active(policy_id, False, ACTOR))

    @router.post("/policies/{policy_id}/manual-request", status_code=201)
    def manual(policy_id: str, body: NoteBody, c: Connector) -> dict[str, str]:
        return {
            "request_id": call(
                c, None, lambda: get_service(c).manual_request(policy_id, ACTOR, body.note)
            )
        }

    @router.post("/policies/{policy_id}/evaluate")
    def evaluate(policy_id: str, c: Connector) -> Evaluation:
        """Explicit evaluation: may create a proposal, NEVER launches (even in automatic mode)."""
        return call(c, None, lambda: get_service(c).evaluate(policy_id, "explicit", ACTOR))

    @router.get("/evaluations")
    def evaluations(
        c: Connector, policy_id: str | None = None, limit: int = Query(50, ge=1, le=500)
    ) -> list[Evaluation]:
        return get_service(c).store.evaluations(policy_id, limit)

    @router.get("/proposals")
    def proposals(
        c: Connector, policy_id: str | None = None, status: str | None = None
    ) -> list[Proposal]:
        return get_service(c).store.proposals(policy_id, status)

    @router.get("/proposals/{proposal_id}")
    def proposal(proposal_id: str, c: Connector) -> Proposal:
        p = get_service(c).store.proposal(proposal_id)
        if p is None:
            raise HTTPException(404, f"unknown proposal {proposal_id}")
        return p

    @router.post("/proposals/{proposal_id}/accept")
    def accept(proposal_id: str, body: NoteBody, c: Connector) -> Proposal:
        """Human acceptance: launches through TrainingService.launch (refused without the lock)."""
        return call(c, None, lambda: get_service(c).accept(proposal_id, ACTOR, body.note))

    @router.post("/proposals/{proposal_id}/reject")
    def reject(proposal_id: str, body: NoteBody, c: Connector) -> Proposal:
        return call(c, None, lambda: get_service(c).reject(proposal_id, ACTOR, body.note))

    @router.post("/proposals/{proposal_id}/reconcile")
    def reconcile(proposal_id: str, c: Connector) -> Proposal:
        return call(c, None, lambda: get_service(c).reconcile(proposal_id, ACTOR))

    @router.get("/ledger")
    def ledger(c: Connector, policy_id: str | None = None) -> list[dict[str, Any]]:
        return get_service(c).store.ledger(policy_id)

    @router.get("/audit")
    def audit(
        c: Connector, policy_id: str | None = None, limit: int = Query(200, ge=1, le=2000)
    ) -> list[dict[str, Any]]:
        return get_service(c).store.audit(policy_id, limit)

    @router.get("/comparison")
    def comparison(model_id: str, version: str, c: Connector, response: Response) -> dict[str, Any]:
        return call(c, response, lambda: get_service(c).comparison(model_id, version))

    return router
