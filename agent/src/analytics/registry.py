"""Recipe registry and runner for local analytics."""

from __future__ import annotations

from typing import Any

from src.analytics.connection import connect_market_db
from src.analytics.models import AnalysisRecipe, AnalyticsError
from src.analytics.top_volume import TOP_VOLUME_RECIPE


_RECIPES: dict[str, AnalysisRecipe] = {
    TOP_VOLUME_RECIPE.id: TOP_VOLUME_RECIPE,
}


def list_recipes() -> list[dict[str, Any]]:
    """Return analytics recipes available to Web and Agent callers."""
    return [recipe.to_dict() for recipe in _RECIPES.values()]


def get_recipe(recipe_id: str) -> AnalysisRecipe:
    """Return a registered analytics recipe."""
    try:
        return _RECIPES[recipe_id]
    except KeyError as exc:
        available = ", ".join(sorted(_RECIPES))
        raise AnalyticsError(f"Unknown analytics recipe '{recipe_id}'. Available: {available}") from exc


def run_analysis(
    recipe_id: str,
    params: dict[str, Any] | None = None,
    *,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Run a registered recipe and return a serializable analytics result."""
    recipe = get_recipe(recipe_id)
    effective_params = dict(recipe.default_params)
    if params:
        effective_params.update(params)

    if conn is not None:
        return recipe.runner(conn, effective_params)

    owned_conn = connect_market_db()
    try:
        return recipe.runner(owned_conn, effective_params)
    finally:
        owned_conn.close()
