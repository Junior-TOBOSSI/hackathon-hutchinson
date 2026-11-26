"""TEMPORARY ARGOS entry point: the historical API + the Production Engine.

    uvicorn visionhub.argos_app:app

It exists because ``visionhub/api.py`` is protected (see AGENTS.md). Once the team agrees,
two lines in ``create_app`` (import + ``install_production(app, settings)``) replace this
file, which can then be deleted.
"""

from __future__ import annotations

from fastapi import FastAPI

from visionhub.api import create_app
from visionhub.config import Settings
from visionhub.production.router import install_production


def create_argos_app(settings: Settings | None = None, **kwargs) -> FastAPI:
    settings = settings or Settings()
    return install_production(create_app(settings), settings, **kwargs)


app = create_argos_app()
