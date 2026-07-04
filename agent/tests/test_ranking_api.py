"""Regression tests for the local stock ranking API."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import api_server
from src.data.storage import Storage


def _use_ranking_db(monkeypatch):
    storage = Storage(db_path=":memory:")
    monkeypatch.setattr(api_server, "_connect_ranking_db", lambda: storage.conn)
    return storage


def test_top_volume_uses_last_n_trading_days(monkeypatch) -> None:
    """The ranking window is exactly the requested number of trading days."""
    storage = _use_ranking_db(monkeypatch)
    storage.upsert_stock_info(
        [
            {
                "code": "000001.SZ",
                "name": "Old Volume",
                "market": "SZ",
                "source": "test",
            },
            {
                "code": "000002.SZ",
                "name": "Recent Volume",
                "market": "SZ",
                "source": "test",
            },
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
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get("/ranking/top-volume?days=2&limit=2")

    assert response.status_code == 200
    body = response.json()
    assert [row["code"] for row in body] == ["000002.SZ", "000001.SZ"]
    assert body[0]["total_volume"] == 200.0
    assert body[1]["total_volume"] == 2.0


def test_top_volume_does_not_require_stock_info(monkeypatch) -> None:
    """Daily OHLCV rows should be visible even before stock_info is synced."""
    storage = _use_ranking_db(monkeypatch)
    rows = []
    for trade_date in ("2026-06-08", "2026-06-09"):
        rows.append(
            {
                "code": "000001.SZ",
                "trade_date": trade_date,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10.0,
                "amount": 10.0,
            }
        )
    storage.upsert_daily(pd.DataFrame(rows), source="test")
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get("/ranking/top-volume?days=2&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["code"] == "000001.SZ"
    assert body[0]["name"] == "000001.SZ"


def test_top_volume_reports_storage_errors(monkeypatch) -> None:
    """DuckDB failures should surface as errors instead of empty rankings."""
    monkeypatch.setattr(
        api_server,
        "_connect_ranking_db",
        lambda: (_ for _ in ()).throw(RuntimeError("database is locked")),
        raising=False,
    )
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))

    response = client.get("/ranking/top-volume?days=2&limit=5")

    assert response.status_code == 503
    assert "Ranking data unavailable" in response.json()["detail"]


def test_connect_ranking_db_uses_read_only_connection(monkeypatch) -> None:
    """Ranking opens the market database read-only so read-only DB access works."""
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_connect(path: str, **kwargs):
        calls.append((path, kwargs))
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(duckdb, "connect", fake_connect)

    with pytest.raises(RuntimeError, match="stop after capture"):
        api_server._connect_ranking_db()

    assert calls
    assert calls[0][1]["read_only"] is True
