"""Tests for TDX and THS data sources (metadata + import checks)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.sources.tdx_source import TdxSource, _is_a_share, _is_bj, _to_tdx_symbol
from src.data.sources.tencent_source import _parse_intraday_bars
from src.data.sources.ths_source import ThsSource, _strip_suffix


# ── TDX helpers ─────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "code, expected",
    [
        ("600036.SH", True),
        ("000001.SZ", True),
        ("600036", True),
        ("000001", True),
        ("AAPL", False),
        ("00700.HK", False),
        ("", False),
    ],
)
def test_is_a_share(code: str, expected: bool) -> None:
    assert _is_a_share(code) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "code, expected",
    [
        ("430047.BJ", True),
        ("830799.BJ", True),
        ("430047", True),
        ("600036.SH", False),
        ("000001.SZ", False),
    ],
)
def test_is_bj(code: str, expected: bool) -> None:
    assert _is_bj(code) == expected


@pytest.mark.unit
def test_to_tdx_symbol() -> None:
    assert _to_tdx_symbol("600036.SH") == "600036"
    assert _to_tdx_symbol("000001.SZ") == "000001"
    assert _to_tdx_symbol("600036") == "600036"


# ── TDX source metadata ─────────────────────────────────────────────────


@pytest.mark.unit
def test_tdx_source_metadata() -> None:
    src = TdxSource()
    assert src.name == "tdx"
    assert src.markets == {"a_share"}
    assert src.needs_rate_limit is False


@pytest.mark.unit
def test_tdx_source_is_available() -> None:
    """is_available returns bool. May be True or False depending on env."""
    result = TdxSource().is_available()
    assert isinstance(result, bool)


# ── THS source metadata ────────────────────────────────────────────────


@pytest.mark.unit
def test_ths_source_metadata() -> None:
    src = ThsSource()
    assert src.name == "ths"
    assert "a_share" in src.markets
    assert "hk_equity" in src.markets
    assert src.needs_rate_limit is True


@pytest.mark.unit
def test_ths_source_is_available() -> None:
    result = ThsSource().is_available()
    assert isinstance(result, bool)


@pytest.mark.unit
def test_strip_suffix() -> None:
    assert _strip_suffix("600036.SH") == "600036"
    assert _strip_suffix("00700.HK") == "00700"
    assert _strip_suffix("000001.SZ") == "000001"
    assert _strip_suffix("600036") == "600036"


@pytest.mark.unit
def test_tencent_parse_intraday_accepts_12_digit_datetimes() -> None:
    df = _parse_intraday_bars(
        [
            ["202606241030", "37.49", "37.00", "37.56", "36.94", "381730.00", {}, "18.50"],
            ["202606241500", "36.85", "36.76", "36.85", "36.75", "361399.00", {}, "17.52"],
        ],
        "2026-06-24",
        "2026-06-24",
    )

    assert df is not None
    assert df["trade_date"].tolist() == ["2026-06-24", "2026-06-24"]
    assert df["bar_time"].tolist() == ["10:30", "15:00"]
    assert df["close"].tolist() == [37.00, 36.76]


@pytest.mark.unit
def test_ths_intraday_fetch_uses_requested_interval(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_hist_min_em(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({
            "时间": ["2026-06-12 10:00"],
            "开盘": [10.0],
            "收盘": [10.1],
            "最高": [10.2],
            "最低": [9.9],
            "成交量": [1000],
            "成交额": [10000],
        })

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_zh_a_hist_min_em=fake_hist_min_em))
    src = ThsSource()
    monkeypatch.setattr(src, "_delay", lambda *args, **kwargs: None)

    out = src.fetch_intraday_range(
        ["000001.SZ"],
        "2026-06-12",
        "2026-06-12",
        interval="60m",
    )

    assert calls[0]["period"] == "60"
    assert "000001.SZ" in out


@pytest.mark.unit
def test_ths_normalize_intraday_preserves_bar_dates() -> None:
    df = pd.DataFrame({
        "时间": ["2026-06-10 09:45", "2026-06-11 10:00"],
        "开盘": [10.0, 10.1],
        "收盘": [10.2, 10.3],
        "最高": [10.4, 10.5],
        "最低": [9.9, 10.0],
        "成交量": [1000, 1200],
        "成交额": [10000, 12000],
    })

    out = ThsSource._normalize_intraday("000001.SZ", df)

    assert out is not None
    assert out["trade_date"].tolist() == ["2026-06-10", "2026-06-11"]
    assert out["bar_time"].tolist() == ["09:45", "10:00"]
