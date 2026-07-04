"""Tests for generic analytics API routes."""

from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

import api_server
from src.data.storage import Storage


def _storage_with_daily_rows() -> Storage:
    storage = Storage(db_path=":memory:")
    storage.upsert_stock_info(
        [{"code": "000002.SZ", "name": "Recent Volume", "market": "SZ", "source": "test"}]
    )
    rows = []
    for trade_date in [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-06-01", periods=2)]:
        rows.append(
            {
                "code": "000002.SZ",
                "trade_date": trade_date,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 100.0,
                "amount": 200.0,
            }
        )
    storage.upsert_daily(pd.DataFrame(rows), source="test")
    return storage


def test_analytics_recipes_endpoint_lists_top_volume() -> None:
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    response = client.get("/analytics/recipes")

    assert response.status_code == 200
    body = response.json()
    assert any(recipe["id"] == "top-volume" for recipe in body)


def test_analytics_recipe_endpoint_runs_top_volume(monkeypatch) -> None:
    storage = _storage_with_daily_rows()
    monkeypatch.setattr("src.analytics.registry.connect_market_db", lambda: storage.conn)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    response = client.get("/analytics/top-volume?days=2&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "top-volume"
    assert body["params"] == {"days": 2, "limit": 1}
    assert body["rows"][0]["code"] == "000002.SZ"
    assert body["rows"][0]["total_volume"] == 200.0
