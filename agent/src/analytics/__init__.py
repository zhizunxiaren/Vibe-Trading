"""Reusable local analytics recipes backed by the market DuckDB database."""

from src.analytics.registry import get_recipe, list_recipes, run_analysis
from src.analytics.models import AnalyticsError

__all__ = ["AnalyticsError", "get_recipe", "list_recipes", "run_analysis"]
