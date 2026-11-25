import time

import numpy as np

from visionhub.config import Settings
from visionhub.contracts import (
    Decision,
    FrameMeta,
    OperatorFeedback,
    Thresholds,
    UseCase,
)
from visionhub.pipeline import Pipeline
from visionhub.registry import Registry
from visionhub.store import EventStore

IMAGE = np.zeros((120, 160, 3), dtype=np.uint8)


def make_pipeline(**overrides) -> Pipeline:
    settings = Settings(_env_file=None, db_path=":memory:", **overrides)
    return Pipeline(settings, Registry(settings).load(), EventStore(":memory:"))


def meta(i):
    return FrameMeta(frame_id=f"t-{i}", workstation_id="WS", camera_id="C")


def test_process_frame_produces_one_event_per_use_case():
    pipeline = make_pipeline()
    events = pipeline.process_frame(IMAGE, meta(0))
    assert {e.use_case for e in events} == set(UseCase)
    assert all(e.latency_ms > 0 for e in events)
    assert len(pipeline.store.list()) == 3


def test_process_frame_can_target_one_use_case_without_storing():
    pipeline = make_pipeline()
    events = pipeline.process_frame(IMAGE, meta(0), use_cases=[UseCase.SAFETY], store=False)
    assert [e.use_case for e in events] == [UseCase.SAFETY]
    assert pipeline.store.list() == []


def test_threshold_change_affects_next_decisions():
    pipeline = make_pipeline()
    pipeline.registry.set_thresholds(UseCase.QUALITY, Thresholds(low=0.0, high=0.0))
    events = pipeline.process_frame(IMAGE, meta(1), use_cases=[UseCase.QUALITY])
    assert events[0].decision == Decision.ANOMALIE
    pipeline.registry.set_thresholds(UseCase.QUALITY, Thresholds(low=1.0, high=1.0))
    events = pipeline.process_frame(IMAGE, meta(1), use_cases=[UseCase.QUALITY])
    assert events[0].decision == Decision.CONFORME


def test_store_filters_feedback_and_stats():
    pipeline = make_pipeline()
    for i in range(60):
        pipeline.process_frame(IMAGE, meta(i))
    store = pipeline.store
    assert len(store.list(limit=1000)) == 180
    assert all(e.use_case == UseCase.SAFETY for e in store.list(use_case=UseCase.SAFETY))

    to_review = store.list(decision=Decision.A_VERIFIER, limit=1000)
    assert to_review, "expected some a_verifier events with default thresholds"
    stats = store.stats()
    assert stats.total == 180
    assert stats.pending_review == len(to_review)

    updated = store.set_feedback(to_review[0].event_id, OperatorFeedback(verdict="defaut"))
    assert updated.operator_feedback.verdict == "defaut"
    assert store.get(to_review[0].event_id).operator_feedback.verdict == "defaut"
    assert store.stats().pending_review == len(to_review) - 1
    assert store.set_feedback("unknown", OperatorFeedback(verdict="conforme")) is None


def test_background_loop_runs_and_stops():
    pipeline = make_pipeline(pipeline_fps=50)
    pipeline.start()
    deadline = time.time() + 5
    while pipeline.frames_processed < 3 and time.time() < deadline:
        time.sleep(0.05)
    pipeline.stop()
    assert pipeline.frames_processed >= 3
    assert not pipeline.running
    assert pipeline.last_error is None
