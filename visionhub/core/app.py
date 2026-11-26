"""ARGOS Core HTTP service. Run with uvicorn on 127.0.0.1 only for the MVP."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request

from visionhub.contracts import utc_now
from visionhub.core.store import CoreStorageError, CoreStore
from visionhub.integration.core_api import Alert, OperatorReport, StationSummary
from visionhub.integration.edge_events import EdgeEvent, EdgeEventBatch, IngestAck
from visionhub.production.contracts import Part, ProductionKPI, StationId

StationPath = Annotated[StationId, Path()]
AlertStatus = Literal["open", "acknowledged", "validated", "rejected", "resolved"]


def create_app(
    db_path: str | None = None, *, stale_after_s: int = 120, alert_on_review: bool = True
) -> FastAPI:
    path = db_path or os.environ.get("ARGOS_CORE_DB", "var/argos-core.sqlite3")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.core = CoreStore(
            path, stale_after_s=stale_after_s, alert_on_review=alert_on_review
        )
        try:
            yield
        finally:
            application.state.core.close()

    app = FastAPI(title="ARGOS Core", version="0.1.0", lifespan=lifespan)

    def store(request: Request) -> CoreStore:
        return request.app.state.core

    def require_station(request: Request, station_id: str) -> StationSummary:
        station = store(request).station(station_id)
        if station is None:
            raise HTTPException(404, "unknown station")
        return station

    def window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
        end = end or utc_now()
        start = start or end - timedelta(hours=8)
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(422, "from and to must include a timezone")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if start > end:
            raise HTTPException(422, "from must be no later than to")
        return start, end

    @app.get("/health")
    def health(request: Request) -> dict:
        return store(request).health()

    @app.post("/ingest/v1/events")
    def ingest(request: Request, batch: EdgeEventBatch) -> IngestAck:
        try:
            return store(request).ingest(batch)
        except CoreStorageError as exc:
            # No ACK is sent when the transaction fails.
            raise HTTPException(503, "Core persistence failed; retry the batch") from exc

    @app.get("/api/v1/stations")
    def stations(request: Request) -> list[StationSummary]:
        return store(request).stations()

    @app.get("/api/v1/stations/{station_id}")
    def station(request: Request, station_id: StationPath) -> StationSummary:
        return require_station(request, station_id)

    @app.get("/api/v1/kpi")
    def global_kpi(
        request: Request,
        start: Annotated[datetime | None, Query(alias="from")] = None,
        end: Annotated[datetime | None, Query(alias="to")] = None,
        station_id: str | None = None,
    ) -> ProductionKPI:
        a, b = window(start, end)
        if station_id:
            require_station(request, station_id)
        return store(request).kpi(a, b, station_id=station_id)

    @app.get("/api/v1/stations/{station_id}/kpi")
    def station_kpi(
        request: Request,
        station_id: StationPath,
        start: Annotated[datetime | None, Query(alias="from")] = None,
        end: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> ProductionKPI:
        require_station(request, station_id)
        a, b = window(start, end)
        return store(request).kpi(a, b, station_id=station_id)

    @app.get("/api/v1/alerts")
    def alerts(
        request: Request,
        status: AlertStatus | None = None,
        station_id: str | None = None,
    ) -> list[Alert]:
        return store(request).alerts(status=status, station_id=station_id)

    @app.post("/api/v1/alerts/{alert_id}/{action}")
    def change_alert(
        request: Request,
        alert_id: str,
        action: Literal["acknowledge", "validate", "reject", "resolve"],
    ) -> Alert:
        try:
            changed = store(request).change_alert(alert_id, action)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if changed is None:
            raise HTTPException(404, "unknown alert")
        return changed

    @app.get("/api/v1/events")
    def events(
        request: Request,
        station_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[EdgeEvent]:
        return store(request).events(station_id=station_id, limit=limit)

    @app.get("/api/v1/parts")
    def parts(
        request: Request,
        station_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[Part]:
        return store(request).parts(station_id=station_id, limit=limit)

    @app.get("/api/v1/operator-reports")
    def operator_reports(request: Request) -> list[OperatorReport]:
        return store(request).reports()

    @app.get("/api/v1/stations/{station_id}/model-status")
    def model_status(request: Request, station_id: StationPath) -> list[dict]:
        require_station(request, station_id)
        return store(request).model_status(station_id)

    return app


app = create_app()
