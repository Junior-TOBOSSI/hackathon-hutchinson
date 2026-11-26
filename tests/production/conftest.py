from datetime import UTC, datetime, timedelta

import pytest

from visionhub.config import Settings
from visionhub.contracts import UseCase
from visionhub.pipeline import Pipeline
from visionhub.production.engine import ProductionEngine
from visionhub.production.store import ProductionStore
from visionhub.registry import Registry
from visionhub.store import EventStore


class FakeClock:
    """Controllable UTC clock."""

    def __init__(self, start=datetime(2026, 1, 5, 6, 0, tzinfo=UTC)):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_engine(tmp_path, clock):
    """Build engines on a temporary database file; close everything afterwards."""
    opened = []

    def factory(enabled=tuple(UseCase), db_name="argos.db"):
        settings = Settings(
            _env_file=None,
            db_path=str(tmp_path / db_name),
            pipeline_enabled=False,
            enabled_use_cases=list(enabled),
        )
        registry = Registry(settings).load()
        events = EventStore(settings.db_path)
        store = ProductionStore(settings.db_path)
        opened.extend([events, store])
        engine = ProductionEngine(store, registry, Pipeline(settings, registry, events), clock)
        engine.events = events  # handy for assertions on the inference events
        return engine

    yield factory
    for resource in opened:
        resource.close()


@pytest.fixture
def spy():
    """Wrap an analyzer instance's analyze() to record calls (and optionally fail)."""

    def install(analyzer, calls: list, raises: Exception | None = None):
        original = analyzer.analyze

        def wrapped(image, meta):
            calls.append(meta.frame_id)
            if raises is not None:
                raise raises
            return original(image, meta)

        analyzer.analyze = wrapped

    return install
