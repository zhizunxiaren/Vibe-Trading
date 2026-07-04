"""Shared models for local analytics recipes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class AnalyticsError(ValueError):
    """Raised for invalid analytics requests."""


@dataclass(frozen=True)
class AnalyticsColumn:
    """Column metadata used by API clients and Web tables."""

    key: str
    label: str
    type: str = "string"
    align: str = "left"

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "align": self.align,
        }


RecipeRunner = Callable[[Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AnalysisRecipe:
    """Registered executable analytics recipe."""

    id: str
    title: str
    description: str
    default_params: dict[str, Any]
    columns: tuple[AnalyticsColumn, ...]
    runner: RecipeRunner

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "default_params": dict(self.default_params),
            "columns": [column.to_dict() for column in self.columns],
        }
