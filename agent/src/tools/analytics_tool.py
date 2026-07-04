"""Agent tools for local analytics recipes."""

from __future__ import annotations

import json
from typing import Any, Callable

from src.agent.tools import BaseTool
from src.analytics import AnalyticsError, list_recipes, run_analysis


class ListAnalyticsRecipesTool(BaseTool):
    """List locally registered analytics recipes."""

    name = "list_analytics_recipes"
    description = (
        "List local read-only analytics recipes that can run against the "
        "configured DuckDB market database."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, **_: Any) -> str:
        return json.dumps(
            {"status": "ok", "recipes": list_recipes()},
            ensure_ascii=False,
            indent=2,
        )


class RunAnalysisTool(BaseTool):
    """Run a local read-only analytics recipe."""

    name = "run_analysis"
    description = (
        "Run a registered local read-only analytics recipe against the "
        "configured DuckDB market database. Use recipe_id='top-volume' with "
        "params {'days': 20, 'limit': 100} for the 20 trading-day volume ranking."
    )
    parameters = {
        "type": "object",
        "properties": {
            "recipe_id": {
                "type": "string",
                "description": "Registered recipe id, e.g. 'top-volume'.",
            },
            "params": {
                "type": "object",
                "description": "Recipe parameters. For top-volume: days and limit.",
                "additionalProperties": True,
                "default": {},
            },
        },
        "required": ["recipe_id"],
    }

    def __init__(self, conn_factory: Callable[[], Any] | None = None) -> None:
        self.conn_factory = conn_factory

    def execute(self, **kwargs: Any) -> str:
        recipe_id = str(kwargs["recipe_id"])
        params = kwargs.get("params") or {}
        try:
            if self.conn_factory is not None:
                result = run_analysis(recipe_id, params, conn=self.conn_factory())
            else:
                result = run_analysis(recipe_id, params)
        except AnalyticsError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error_type": "invalid_request",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        return json.dumps({"status": "ok", "result": result}, ensure_ascii=False, indent=2)
