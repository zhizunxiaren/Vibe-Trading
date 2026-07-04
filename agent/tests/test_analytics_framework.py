"""Tests for the reusable local analytics framework."""

from __future__ import annotations

import json

import pandas as pd

from src.analytics import list_recipes, run_analysis
from src.data.storage import Storage
from src.tools import build_filtered_registry


def _storage_with_daily_rows() -> Storage:
    storage = Storage(db_path=":memory:")
    storage.upsert_stock_info(
        [
            {"code": "000001.SZ", "name": "Old Volume", "market": "SZ", "source": "test"},
            {"code": "000002.SZ", "name": "Recent Volume", "market": "SZ", "source": "test"},
        ]
    )
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-06-01", periods=10)]
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        is_recent = index >= len(dates) - 2
        rows.append(
            {
                "code": "000001.SZ",
                "trade_date": trade_date,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0 if is_recent else 1000.0,
                "amount": 1.0 if is_recent else 1000.0,
            }
        )
        rows.append(
            {
                "code": "000002.SZ",
                "trade_date": trade_date,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100.0 if is_recent else 1.0,
                "amount": 100.0 if is_recent else 1.0,
            }
        )
    storage.upsert_daily(pd.DataFrame(rows), source="test")
    return storage


def test_list_recipes_exposes_top_volume_metadata() -> None:
    recipes = list_recipes()

    top_volume = next(recipe for recipe in recipes if recipe["id"] == "top-volume")
    assert top_volume["title"] == "Top Volume"
    assert top_volume["default_params"] == {"days": 20, "limit": 100}
    assert [column["key"] for column in top_volume["columns"]][:4] == [
        "rank",
        "code",
        "name",
        "total_volume",
    ]


def test_run_top_volume_uses_registered_recipe_and_recent_window() -> None:
    storage = _storage_with_daily_rows()

    result = run_analysis("top-volume", {"days": 2, "limit": 2}, conn=storage.conn)

    assert result["id"] == "top-volume"
    assert result["params"] == {"days": 2, "limit": 2}
    assert result["meta"]["trade_days"] == 2
    assert result["meta"]["window_start"] == "2026-06-11"
    assert result["meta"]["window_end"] == "2026-06-12"
    assert [row["code"] for row in result["rows"]] == ["000002.SZ", "000001.SZ"]
    assert result["rows"][0]["rank"] == 1
    assert result["rows"][0]["total_volume"] == 200.0
    assert result["rows"][1]["total_volume"] == 2.0


def test_run_analysis_tool_calls_same_recipe() -> None:
    storage = _storage_with_daily_rows()
    registry = build_filtered_registry(["run_analysis"])
    tool = registry.get("run_analysis")
    assert tool is not None
    tool.conn_factory = lambda: storage.conn

    payload = json.loads(
        tool.execute(recipe_id="top-volume", params={"days": 2, "limit": 1})
    )

    assert payload["status"] == "ok"
    assert payload["result"]["id"] == "top-volume"
    assert payload["result"]["rows"][0]["code"] == "000002.SZ"
