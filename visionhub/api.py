"""HTTP API (FastAPI). The analysis pipeline runs in a background thread at startup.

Run it with:  uvicorn visionhub.api:app   (interactive docs at /docs)
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile

from visionhub import __version__
from visionhub.config import Settings
from visionhub.contracts import (
    Decision,
    Event,
    FeedbackIn,
    FrameMeta,
    OperatorFeedback,
    Stats,
    Thresholds,
    UseCase,
    UseCaseInfo,
)
from visionhub.pipeline import Pipeline
from visionhub.registry import Registry
from visionhub.store import EventStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        registry = Registry(settings).load()
        store = EventStore(settings.db_path)
        pipeline = Pipeline(settings, registry, store)
        app.state.registry, app.state.store, app.state.pipeline = registry, store, pipeline
        if settings.pipeline_enabled:
            pipeline.start()
        yield
        pipeline.stop()
        store.close()

    app = FastAPI(title="visionhub", version=__version__, lifespan=lifespan)

    def pipeline_of(request: Request) -> Pipeline:
        return request.app.state.pipeline

    def require_loaded(request: Request, use_case: UseCase) -> None:
        if request.app.state.registry.get(use_case) is None:
            raise HTTPException(404, f"Use case {use_case.value!r} is not loaded")

    @app.get("/health")
    def health(request: Request) -> dict:
        pipeline = pipeline_of(request)
        return {
            "status": "ok",
            "version": __version__,
            "device": settings.device,
            "source": settings.source,
            "pipeline_running": pipeline.running,
            "frames_processed": pipeline.frames_processed,
            "pipeline_error": pipeline.last_error,
        }

    @app.get("/use-cases")
    def use_cases(request: Request) -> list[UseCaseInfo]:
        return request.app.state.registry.info()

    @app.get("/events")
    def events(
        request: Request,
        use_case: UseCase | None = None,
        decision: Decision | None = None,
        pending_feedback: bool | None = Query(
            None, description="true = only events without operator feedback"
        ),
        limit: int = Query(50, ge=1, le=1000),
    ) -> list[Event]:
        return request.app.state.store.list(use_case, decision, pending_feedback, limit)

    @app.get("/stats")
    def stats(request: Request) -> Stats:
        return request.app.state.store.stats()

    @app.post("/analyze")
    def analyze(
        request: Request,
        image: UploadFile = File(..., description="JPEG/PNG image"),
        use_case: UseCase | None = Query(None, description="Empty = all loaded analyzers"),
        store: bool = Query(False, description="Also store the resulting events"),
    ) -> list[Event]:
        if use_case is not None:
            require_loaded(request, use_case)
        buffer = np.frombuffer(image.file.read(), dtype=np.uint8)
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR) if buffer.size else None
        if decoded is None:
            raise HTTPException(400, "Cannot decode the uploaded file as an image")
        meta = FrameMeta(
            frame_id=f"upload-{uuid.uuid4().hex[:8]}",
            workstation_id=settings.workstation_id,
            camera_id="upload",
        )
        targets = [use_case] if use_case else None
        return pipeline_of(request).process_frame(decoded, meta, targets, store=store)

    @app.put("/thresholds/{use_case}")
    def set_thresholds(request: Request, use_case: UseCase, thresholds: Thresholds) -> UseCaseInfo:
        require_loaded(request, use_case)
        registry: Registry = request.app.state.registry
        registry.set_thresholds(use_case, thresholds)
        return next(i for i in registry.info() if i.use_case == use_case)

    @app.post("/events/{event_id}/feedback")
    def feedback(request: Request, event_id: str, body: FeedbackIn) -> Event:
        store: EventStore = request.app.state.store
        event = store.get(event_id)
        if event is None:
            raise HTTPException(404, "Unknown event")
        if event.decision != Decision.A_VERIFIER:
            raise HTTPException(409, "Feedback is only accepted on 'a_verifier' events")
        return store.set_feedback(event_id, OperatorFeedback(**body.model_dump()))

    return app


app = create_app()
