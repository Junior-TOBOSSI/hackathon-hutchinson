"""DBX-07B Monitoring routes (``/api/mlops/monitoring/...``) and overview v2
(``/api/mlops/overview/v2``), included by the MLOps router.

- GET requests NEVER write (no snapshot, no alert, no reference is created by a read);
- the only writes are explicit POSTs: ``/references`` (freeze an immutable reference) and
  ``/collect`` (idempotent collection of daily snapshots and alerts) — all local (SQLite);
- Databricks reads go through the DBX-PERF-01 request scope (cache, budget, freshness headers);
- DTOs are monitoring-specific (plain dicts documented in docs/dbx-07b-monitoring.md): the
  shared contracts (``MonitoringMetrics``...) are not changed.
"""

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from mlops.databricks.connector import DatabricksConnector, DatabricksConnectorError
from mlops.databricks.read_cache import BudgetExceeded, read_scope
from mlops.monitoring.service import MonitoringService, observations, select, source_block

_LOCK = threading.Lock()
DataKind = Literal["real", "simulated", "all"]


def monitoring_for(c: DatabricksConnector) -> MonitoringService:
    svc = getattr(c, "_monitoring_service", None)
    if svc is None:
        with _LOCK:
            svc = getattr(c, "_monitoring_service", None)
            if svc is None:
                svc = MonitoringService(c)
                c._monitoring_service = svc
    return svc


class ReferenceBody(BaseModel):
    source: Literal["offline_test", "operational_window"]
    model_id: str | None = None  # offline_test: registered model id
    model_key: str | None = None  # operational_window: monitoring model key
    version: str
    start: datetime | None = None
    end: datetime | None = None
    data_kind: Literal["real", "simulated"] | None = None


def create_monitoring_router(
    get_connector: Callable[[], DatabricksConnector],
    get_service: Callable[[DatabricksConnector], MonitoringService] = monitoring_for,
    get_policy: Callable[[str], Any] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["monitoring"])
    Connector = Annotated[DatabricksConnector, Depends(get_connector)]
    Kind = Annotated[DataKind, Query(description="real | simulated | all (never mixed silently)")]

    def call(
        c: DatabricksConnector, response: Response | None, fresh: bool, fn: Callable[[], Any]
    ) -> Any:
        try:
            with read_scope(fresh=fresh, budget=c.settings.request_budget_seconds) as scope:
                result = fn()
            if response is not None:
                response.headers.update(scope.headers())
            return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except DatabricksConnectorError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        except BudgetExceeded as exc:
            raise HTTPException(503, f"Databricks too slow: {exc}") from exc

    p = "/mlops/monitoring"

    @router.get(f"{p}/summary")
    def summary(
        c: Connector, response: Response, data_kind: Kind = "all", fresh: bool = False
    ) -> dict[str, Any]:
        return call(c, response, fresh, lambda: get_service(c).summary(data_kind))

    def filters(
        data_kind: Kind = "all",
        station: str | None = None,
        model_key: str | None = None,
        version: str | None = None,
        use_case: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "data_kind": data_kind,
            "station": station,
            "key": model_key,
            "version": version,
            "use_case": use_case,
            "start": start,
            "end": end,
        }

    Filters = Annotated[dict[str, Any], Depends(filters)]

    @router.get(f"{p}/models")
    def models(
        c: Connector, response: Response, f: Filters, fresh: bool = False
    ) -> list[dict[str, Any]]:
        """Catalogue (filters: data_kind, use_case, station, start, end)."""
        return call(
            c,
            response,
            fresh,
            lambda: get_service(c).models(
                f["data_kind"],
                use_case=f["use_case"],
                station=f["station"],
                start=f["start"],
                end=f["end"],
            ),
        )

    @router.get(f"{p}/models/{{model_key:path}}")
    def model(
        model_key: str,
        c: Connector,
        response: Response,
        data_kind: Kind = "all",
        fresh: bool = False,
    ) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            svc = get_service(c)
            row = next((m for m in svc.models(data_kind) if m["model_key"] == model_key), None)
            if row is None:
                raise LookupError(f"unknown monitoring model key {model_key}")
            return {
                **row,
                "references": [
                    {k: v for k, v in r.items() if k not in ("scores", "latencies")}
                    for r in svc.store.references(model_key)
                ],
                "alerts": [a for a in svc.store.alerts() if a["model_key"] == model_key],
            }

        return call(c, response, fresh, load)

    @router.get(f"{p}/inferences")
    def inferences(
        c: Connector, response: Response, f: Filters, fresh: bool = False
    ) -> dict[str, Any]:
        """Operational aggregates per model / version / station over the window."""
        return call(c, response, fresh, lambda: get_service(c).operational(**f))

    @router.get(f"{p}/human")
    def human(c: Connector, response: Response, f: Filters, fresh: bool = False) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            op = get_service(c).operational(**f)
            return {
                "status": op["status"],
                "sources": op["sources"],
                "data_kind": f["data_kind"],
                **op["human"],
            }

        return call(c, response, fresh, load)

    @router.get(f"{p}/performance/{{model_id}}")
    def performance(
        model_id: str, c: Connector, response: Response, fresh: bool = False
    ) -> dict[str, Any]:
        return call(c, response, fresh, lambda: get_service(c).performance(model_id))

    @router.get(f"{p}/drift")
    def drift(
        c: Connector,
        response: Response,
        model_key: str,
        version: str,
        data_kind: Literal["real", "simulated"] = "real",
        reference_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Computed on demand against a stored reference; writes nothing."""

        def load() -> dict[str, Any]:
            svc = get_service(c)
            refs = [
                r
                for r in svc.store.references()
                if (reference_id and r["reference_id"] == reference_id)
                or (
                    not reference_id
                    and r["model_key"] == model_key
                    and str(r["model_version"]) == version
                )
            ]
            if not refs:
                return {
                    "status": "reference_absent",
                    "model_key": model_key,
                    "version": version,
                    "detail": "freeze a reference first (POST /api/mlops/monitoring/references)",
                }
            ref = refs[-1]
            infs, _, _ = observations(svc._snapshot())
            pop = select(
                infs, data_kind=data_kind, key=model_key, version=version, start=start, end=end
            )
            score_def = f"{model_key}: Core inference score"  # population = Core inferences
            result = svc.drift(ref, pop, model_key, version, data_kind == "simulated", score_def)
            return {
                **result,
                "model_key": model_key,
                "version": version,
                "data_kind": data_kind,
                "core_status": svc._snapshot().status.status,
            }

        return call(c, response, fresh, load)

    @router.get(f"{p}/alerts")
    def alerts(
        c: Connector, state: Literal["open", "resolved"] | None = None
    ) -> list[dict[str, Any]]:
        return get_service(c).store.alerts(state)

    @router.get(f"{p}/history")
    def history(
        c: Connector,
        scope_key: str | None = None,
        data_kind: Literal["real", "simulated"] | None = None,
    ) -> dict[str, Any]:
        svc = get_service(c)
        return {
            "snapshots": svc.store.snapshots(scope_key, data_kind),
            "collections": svc.store.collections(),
        }

    @router.get(f"{p}/references")
    def references(c: Connector, model_key: str | None = None) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in r.items() if k not in ("scores", "latencies")}
            for r in get_service(c).store.references(model_key)
        ]

    @router.post(f"{p}/references", status_code=201)
    def freeze(body: ReferenceBody, c: Connector) -> dict[str, Any]:
        """Explicit freeze of an IMMUTABLE reference (a second identical freeze is refused)."""

        def load() -> dict[str, Any]:
            svc = get_service(c)
            if body.source == "offline_test":
                if not body.model_id:
                    raise HTTPException(400, "model_id is required for an offline_test reference")
                ref = svc.offline_reference(body.model_id, body.version)
            else:
                if not (body.model_key and body.start and body.end and body.data_kind):
                    raise HTTPException(400, "model_key, start, end and data_kind are required")
                ref = svc.operational_reference(
                    body.model_key, body.version, body.start, body.end, body.data_kind
                )
            return {k: v for k, v in ref.items() if k not in ("scores", "latencies")}

        return call(c, None, False, load)

    @router.post(f"{p}/collect")
    def collect(c: Connector) -> dict[str, Any]:
        """Explicit and idempotent (re-running recomputes the same daily windows)."""
        return call(c, None, True, lambda: get_service(c).collect())

    @router.get(f"{p}/retraining-signals/{{model_id}}")
    def retraining_signals(
        model_id: str, c: Connector, response: Response, fresh: bool = False
    ) -> dict[str, Any]:
        def load() -> dict[str, Any]:
            managed = next((m for m in c.settings.models if m.id == model_id), None)
            if managed is None:
                raise LookupError(f"unknown model {model_id}")
            policy = get_policy(managed.argos_use_case) if get_policy else None
            return get_service(c).retraining_signals(model_id, policy)

        return call(c, response, fresh, load)

    @router.get("/mlops/overview/v2")
    def overview_v2(c: Connector, response: Response, fresh: bool = False) -> dict[str, Any]:
        """One block per source, each with its own status and freshness: a failing source
        never hides the others."""

        def load() -> dict[str, Any]:
            svc = get_service(c)
            blocks = [
                source_block("datasets", lambda: _datasets(c)),
                source_block("training", lambda: svc.training.kpis().model_dump()),
                source_block("registry", lambda: _registry(c)),
                _deployment(svc),
                source_block("monitoring", lambda: svc.summary("all")),
                source_block("stations", lambda: _stations(svc)),
            ]
            for b in blocks:
                data = b.get("data") or {}
                if b["status"] == "available" and isinstance(data, dict):
                    if data.get("status") in ("partial", "unavailable"):
                        b["status"] = data["status"]
                    elif data.get("simulated_only"):
                        b["status"] = "simulated"
            return {"blocks": blocks}

        return call(c, response, fresh, load)

    return router


def _datasets(c: DatabricksConnector) -> dict[str, Any]:
    from mlops.databricks.datasets import dataset_store

    fams = dataset_store(c).catalog()
    return {
        "families": len(fams),
        "items": [{"id": f.dataset_id, "latest": getattr(f, "latest_version", None)} for f in fams],
    }


def _registry(c: DatabricksConnector) -> dict[str, Any]:
    rows = []
    for m in c.settings.models:
        st = c.model_status(m.id)
        rows.append(
            {
                "model_id": m.id,
                "uc_name": m.uc_name,
                "versions": len(st.versions),
                "champion": st.aliases.get("champion"),
                "served": {k: v for k, v in st.served.items() if v},
                "approved": [v.version.version for v in st.versions if v.approved],
                "synthetic": m.synthetic,
            }
        )
    return {"models": rows}


def _deployment(svc: MonitoringService) -> dict[str, Any]:
    from mlops.monitoring.service import now_iso

    _, status = svc.deployment.desired()
    return {
        "name": "deployment",
        "status": status.status,
        "fetched_at": now_iso(),
        "detail": status.detail,
        "optional": True,
    }


def _stations(svc: MonitoringService) -> dict[str, Any]:
    snap = svc._snapshot()
    return {
        "status": snap.status.status,
        "fetched_at": snap.status.fetched_at,
        "detail": snap.status.detail,
        "stations": len(snap.stations),
        "online": sum(1 for s in snap.stations if s.get("online")),
        "simulated_only": bool(snap.stations) and all(s.get("simulated") for s in snap.stations),
        "truncated_stations": snap.truncated_stations,
    }
