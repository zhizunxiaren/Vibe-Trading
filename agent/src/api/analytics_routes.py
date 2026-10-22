"""Local market-data analytics and ranking HTTP routes.

Fork-local surface: these endpoints are **not** part of upstream Vibe-Trading.
They expose the local ``src.analytics`` recipe registry over the DuckDB market
database populated by ``python -m src.data download``.

Mounted by ``agent/api_server.py`` via ``register_analytics_routes(app, ...)``,
following the ``alpha_routes.py`` / ``options_routes.py`` slice pattern so the
thin assembler keeps matching upstream.

Routes (auth via the caller-supplied ``require_auth`` dependency):

- ``GET /analytics/recipes``        — list registered local recipes
- ``GET /analytics/{recipe_id}``    — run one recipe with query-string params
- ``GET /ranking/top-volume``       — top symbols by aggregated volume/amount

Error surface:

- A recipe-level ``AnalyticsError`` (unknown recipe, bad params) → 400 with the
  message as ``detail``.
- Any other recipe failure (missing or unreadable database) → 503 with a
  generic ``Analytics data unavailable`` detail; the traceback stays in the log.
- A ranking failure (DuckDB open/read) → 503 with ``Ranking data unavailable``,
  so a broken database never masquerades as an empty ranking.
- ``/ranking/top-volume`` returns an empty list when the database is readable
  but holds no data for the window, so the Web UI can render a "no data yet"
  state instead of an error.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

AuthDep = Callable[..., Awaitable[Any] | Any]


class RankingItem(BaseModel):
    rank: int
    code: str
    name: str
    total_volume: float
    total_amount: float
    float_market_cap: float = 0.0


def _connect_ranking_db():
    """Open the market database read-only for ranking views."""
    from src.analytics.connection import connect_market_db

    return connect_market_db()


def _resolve_connect_ranking_db() -> Callable[[], Any]:
    """Resolve the ranking connection factory from the host module when present.

    Tests and callers patch ``api_server._connect_ranking_db``; reading it from
    the host keeps that seam working now that the route lives in its own module.
    Falls back to this module's own definition when the host has no override.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    override = getattr(host, "_connect_ranking_db", None) if host is not None else None
    if override is not None and override is not _connect_ranking_db:
        return override
    return _connect_ranking_db


def register_analytics_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the local analytics and ranking routes onto ``app``.

    Args:
        app: The host FastAPI app.
        require_auth: Header-auth dependency for every endpoint. When omitted,
            it is resolved from the host ``api_server`` module via
            ``sys.modules`` for backwards compatibility; prefer the explicit
            form in new call sites.
    """
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover — only on unusual import setups
            raise RuntimeError(
                "register_analytics_routes: api_server module not in sys.modules; "
                "pass require_auth explicitly"
            )
        require_auth = host.require_auth

    @app.get(
        "/analytics/recipes",
        dependencies=[Depends(require_auth)],
    )
    async def analytics_recipes():
        """List registered local analytics recipes."""
        from src.analytics import list_recipes

        return list_recipes()

    @app.get(
        "/analytics/{recipe_id}",
        dependencies=[Depends(require_auth)],
    )
    async def analytics_run(recipe_id: str, request: Request):
        """Run a registered local analytics recipe."""
        from src.analytics import AnalyticsError, run_analysis

        try:
            return run_analysis(recipe_id, dict(request.query_params))
        except AnalyticsError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception as exc:  # noqa: BLE001 — never leak a stack frame to clients
            logger.exception("analytics_run failed for recipe %s", recipe_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Analytics data unavailable: {exc}",
            ) from exc

    @app.get(
        "/ranking/top-volume",
        response_model=list[RankingItem],
        dependencies=[Depends(require_auth)],
    )
    async def ranking_top_volume(
        days: int = Query(20, ge=1, le=120, description="Trading days to aggregate"),
        limit: int = Query(100, ge=1, le=200, description="Max results"),
    ):
        """Top symbols by total volume over the last N trading days.

        Reads the DuckDB database populated by ``python -m src.data download``
        and returns an empty list when no data is available.
        """
        limit = min(max(1, limit), 200)
        try:
            conn = _resolve_connect_ranking_db()()
            try:
                from src.analytics import run_analysis

                analysis = run_analysis(
                    "top-volume", {"days": days, "limit": limit}, conn=conn
                )
            finally:
                conn.close()

            results: list[RankingItem] = []
            for row in analysis["rows"]:
                results.append(
                    RankingItem(
                        rank=int(row["rank"]),
                        code=str(row["code"]),
                        name=str(row["name"]),
                        total_volume=float(row["total_volume"] or 0),
                        total_amount=float(row["total_amount"] or 0),
                        float_market_cap=float(row["float_market_cap"] or 0),
                    )
                )
            return results
        except Exception as exc:  # noqa: BLE001 — never leak a stack frame to clients
            logger.exception("ranking_top_volume failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Ranking data unavailable: {exc}",
            ) from exc
