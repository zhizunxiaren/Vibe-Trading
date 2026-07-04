"""Regression tests for downloader orchestration."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data.downloader import Downloader, get_downloader
from src.data.sources.base import BaseDataSource
from src.data.storage import Storage


class _BaseFakeSource(BaseDataSource):
    name = "fake"
    markets = {"a_share"}
    needs_rate_limit = False

    def is_available(self) -> bool:
        return True

    def fetch_symbols(self, market: str) -> list[str]:
        _ = market
        return []

    def fetch_intraday_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "15m",
    ) -> dict[str, pd.DataFrame]:
        _ = codes, start_date, end_date, interval
        return {}

    def fetch_capital_flow(
        self,
        codes: list[str],
        trade_date: str,
    ) -> dict[str, pd.DataFrame]:
        _ = codes, trade_date
        return {}


class _EmptyDailySource(_BaseFakeSource):
    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        _ = codes, start_date, end_date
        return {}


class _RangeDailySource(_BaseFakeSource):
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str, str]] = []

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        self.calls.append((tuple(codes), start_date, end_date))
        dates = pd.date_range(start=start_date, end=end_date, freq="D")
        out: dict[str, pd.DataFrame] = {}
        for code in codes:
            out[code] = pd.DataFrame({
                "trade_date": dates.strftime("%Y-%m-%d"),
                "open": [10.0] * len(dates),
                "high": [10.5] * len(dates),
                "low": [9.8] * len(dates),
                "close": [10.2] * len(dates),
                "volume": [1_000_000.0] * len(dates),
                "amount": [10_000_000.0] * len(dates),
            })
        return out


@pytest.fixture
def storage() -> Storage:
    return Storage(db_path=":memory:")


@pytest.mark.unit
def test_run_marks_symbols_missing_from_source_result_as_failed(storage: Storage) -> None:
    dl = Downloader(_EmptyDailySource(), storage=storage)

    result = dl.run(
        "a_share",
        start_date="2026-06-01",
        end_date="2026-06-02",
        symbols=["600036.SH", "000001.SZ"],
    )

    assert result.status == "failed"
    assert result.symbols_ok == 0
    assert result.symbols_failed == 2
    assert "No data" in result.error_msg


@pytest.mark.unit
def test_run_incremental_fetches_from_each_symbol_latest_date(storage: Storage) -> None:
    storage.upsert_daily(pd.DataFrame({
        "code": ["600036.SH", "000001.SZ"],
        "trade_date": ["2026-06-10", "2026-06-08"],
        "open": [10.0, 10.0],
        "high": [10.5, 10.5],
        "low": [9.8, 9.8],
        "close": [10.2, 10.2],
        "volume": [1_000_000.0, 1_000_000.0],
        "amount": [10_000_000.0, 10_000_000.0],
    }), source="seed")
    source = _RangeDailySource()
    dl = Downloader(source, storage=storage)

    result = dl.run(
        "a_share",
        end_date="2026-06-11",
        symbols=["600036.SH", "000001.SZ"],
    )

    assert result.status == "ok"
    lagged = storage.read_daily(["000001.SZ"], start_date="2026-06-09", end_date="2026-06-11")
    assert [d.date() for d in lagged.index] == [
        date(2026, 6, 9),
        date(2026, 6, 10),
        date(2026, 6, 11),
    ]
    assert any(call == (("000001.SZ",), "2026-06-09", "2026-06-11") for call in source.calls)


@pytest.mark.unit
def test_get_downloader_accepts_storage_injection(storage: Storage) -> None:
    dl = get_downloader("tencent", storage=storage)

    assert dl.source.name == "tencent"
    assert dl.storage is storage
