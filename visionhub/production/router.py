"""REST API of the Production Engine, under /production.

Plugged into an existing app with ``install_production(app, settings)``: it wraps the
app lifespan (to open and close the ProductionStore after the registry and the pipeline
exist), mounts the router and maps business errors to HTTP codes. The historical
endpoints are not changed.

Corrections of production parts go ONLY through /production/parts/{id}/corrections.
The historical POST /events/{id}/feedback does not change a part.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, FastAPI, File, Form, Path, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from visionhub.config import Settings
from visionhub.contracts import utc_now
from visionhub.production.contracts import (
    CYCLE_ID_PATTERN,
    STATION_ID_PATTERN,
    Correction,
    CorrectionIn,
    DispositionIn,
    Part,
    PartVerdict,
    ProductionKPI,
    Shift,
    ShiftReport,
    ShiftStart,
)
from visionhub.production.engine import Clock, CycleRequest, ProductionEngine
from visionhub.production.store import (
    ConflictError,
    InvalidOperationError,
    NotFoundError,
    ProductionError,
    ProductionStore,
)

DEFAULT_KPI_WINDOW = timedelta(hours=8)

StationPath = Annotated[str, Path(pattern=STATION_ID_PATTERN)]
Limit = Annotated[int, Query(ge=1, le=1000)]

router = APIRouter(prefix="/production", tags=["production"])


def engine_of(request: Request) -> ProductionEngine:
    return request.app.state.production


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# ------------------------------------------------------------------ cycles and parts


@router.post(
    "/stations/{station_id}/cycles",
    status_code=201,
    responses={
        200: {"description": "Idempotent replay: the cycle already existed"},
        409: {"description": "Same cycle already recorded with another image/camera/source"},
    },
)
def trigger_cycle(
    request: Request,
    response: Response,
    station_id: StationPath,
    cycle_id: Annotated[str, Form(pattern=CYCLE_ID_PATTERN)],
    camera_id: Annotated[str, Form(pattern=STATION_ID_PATTERN)] = "CAM-Q",
    simulated: Annotated[
        bool, Form(description="true = simulated PLC cycle (synthetic image if none sent)")
    ] = False,
    image: Annotated[UploadFile | None, File(description="JPEG/PNG image of the part")] = None,
) -> Part:
    """PLC trigger: inspect one part with the quality analyzer and record it.

    An industrial cycle (simulated=false) without image is recorded as ERROR
    (CAPTURE_FAILED): no synthetic image is ever used for it.
    """
    data = image.file.read() if image is not None else None
    part, replayed = engine_of(request).run_cycle(
        CycleRequest(station_id, cycle_id, camera_id, simulated, data)
    )
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return part


@router.get("/stations/{station_id}/cycles/{cycle_id}")
def get_cycle(request: Request, station_id: StationPath, cycle_id: str) -> Part:
    return engine_of(request).get_part_by_cycle(station_id, cycle_id)


@router.get("/parts")
def list_parts(
    request: Request,
    station_id: str | None = None,
    shift_id: str | None = None,
    verdict: Annotated[PartVerdict | None, Query(description="Effective verdict")] = None,
    limit: Limit = 50,
) -> list[Part]:
    return engine_of(request).store.list_parts(station_id, shift_id, verdict, limit)


@router.get("/parts/{part_id}")
def get_part(request: Request, part_id: str) -> Part:
    return engine_of(request).get_part(part_id)


@router.post("/parts/{part_id}/corrections", status_code=201)
def correct_part(request: Request, part_id: str, body: CorrectionIn) -> Part:
    """Human verdict. Never overwrites the AI prediction; never releases the part."""
    return engine_of(request).correct(part_id, body)


@router.get("/parts/{part_id}/corrections")
def list_corrections(request: Request, part_id: str) -> list[Correction]:
    return engine_of(request).store.list_corrections(part_id)


@router.put("/parts/{part_id}/disposition")
def set_disposition(request: Request, part_id: str, body: DispositionIn) -> Part:
    """Physical disposition reported by the industrial process (not a verdict)."""
    return engine_of(request).set_disposition(part_id, body)


# ------------------------------------------------------------------ shifts and KPIs


@router.post("/stations/{station_id}/shifts", status_code=201)
def start_shift(request: Request, station_id: StationPath, body: ShiftStart) -> Shift:
    return engine_of(request).start_shift(station_id, body)


@router.get("/stations/{station_id}/shifts/current")
def current_shift(request: Request, station_id: StationPath) -> ShiftReport:
    return engine_of(request).current_shift_report(station_id)


@router.post("/shifts/{shift_id}/close")
def close_shift(request: Request, shift_id: str) -> ShiftReport:
    return engine_of(request).close_shift(shift_id)


@router.get("/shifts/{shift_id}")
def get_shift(request: Request, shift_id: str) -> ShiftReport:
    return engine_of(request).shift_report(shift_id)


@router.get("/shifts")
def list_shifts(request: Request, station_id: str | None = None, limit: Limit = 50) -> list[Shift]:
    return engine_of(request).store.list_shifts(station_id, limit)


@router.get("/stations/{station_id}/kpi")
def station_kpi(
    request: Request,
    station_id: StationPath,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> ProductionKPI:
    """KPIs of a station over [from, to). Defaults: the last 8 hours. Naive times = UTC."""
    engine = engine_of(request)
    end = as_utc(end) if end else engine.clock()
    start = as_utc(start) if start else end - DEFAULT_KPI_WINDOW
    return engine.station_kpi(station_id, start, end)


# ------------------------------------------------------------------ wiring

STATUS_BY_ERROR = {NotFoundError: 404, ConflictError: 409, InvalidOperationError: 422}


def _production_error(request: Request, exc: ProductionError) -> JSONResponse:
    status = next((s for cls, s in STATUS_BY_ERROR.items() if isinstance(exc, cls)), 400)
    return JSONResponse(status_code=status, content={"detail": str(exc)})


def install_production(app: FastAPI, settings: Settings, clock: Clock = utc_now) -> FastAPI:
    """Add the Production Engine to an app built by ``visionhub.api.create_app``."""
    base_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        async with base_lifespan(app_) as state:
            store = ProductionStore(settings.db_path)
            app_.state.production = ProductionEngine(
                store, app_.state.registry, app_.state.pipeline, clock
            )
            try:
                yield state
            finally:
                store.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
    app.add_exception_handler(ProductionError, _production_error)
    return app
