"""DBX-09 AI Leader home page API: ``/api/mlops/overview/v2`` (all blocks) and
``/api/mlops/overview/v2/{block}`` (one block, so the page loads them independently).

Read-only: no collection, no evaluation, no launch is ever triggered by these routes.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from mlops.databricks.connector import DatabricksConnector
from mlops.databricks.read_cache import read_scope
from mlops.overview.service import BLOCKS, build


def create_overview_router(get_connector: Callable[[], DatabricksConnector]) -> APIRouter:
    router = APIRouter(prefix="/mlops/overview", tags=["overview"])
    Connector = Annotated[DatabricksConnector, Depends(get_connector)]

    def served(
        c: DatabricksConnector, response: Response, fresh: bool, fn: Callable[[], Any]
    ) -> Any:
        # Blocks never raise; the scope only adds the DBX-PERF-01 freshness headers.
        with read_scope(fresh=fresh, budget=c.settings.request_budget_seconds) as scope:
            result = fn()
        response.headers.update(scope.headers())
        return result

    @router.get("/v2")
    def overview_v2(
        c: Connector,
        response: Response,
        blocks: str | None = Query(None, description="comma-separated subset of blocks"),
        fresh: bool = False,
    ) -> dict[str, Any]:
        names = [b for b in (blocks.split(",") if blocks else BLOCKS) if b in BLOCKS]
        return served(c, response, fresh, lambda: {"blocks": [build(c, n) for n in names]})

    @router.get("/v2/{name}")
    def overview_block(
        name: str, c: Connector, response: Response, fresh: bool = False
    ) -> dict[str, Any]:
        if name not in BLOCKS:
            raise HTTPException(404, f"unknown block {name}; known: {', '.join(BLOCKS)}")
        return served(c, response, fresh, lambda: build(c, name))

    return router
