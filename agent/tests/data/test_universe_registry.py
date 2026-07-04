"""Tests for market-universe helpers and source fallback registry."""

from __future__ import annotations

from datetime import date

import pytest

from src.data.sources.registry import fallback_chain
from src.data.universe import latest_trade_date


@pytest.mark.unit
def test_latest_trade_date_rolls_weekend_back_to_friday() -> None:
    assert latest_trade_date(date(2026, 7, 4)) == "2026-07-03"
    assert latest_trade_date(date(2026, 7, 5)) == "2026-07-03"


@pytest.mark.unit
def test_latest_trade_date_keeps_weekday() -> None:
    assert latest_trade_date(date(2026, 7, 6)) == "2026-07-06"


@pytest.mark.unit
def test_daily_fallback_chain_includes_requested_source_first() -> None:
    assert fallback_chain("tdx") == ["tdx", "tdx_offline", "tencent", "ths"]


@pytest.mark.unit
def test_capital_flow_fallback_chain_only_uses_ths_after_unsupported_sources() -> None:
    assert fallback_chain("tencent", data_type="capital_flow") == ["tencent", "ths"]
    assert fallback_chain("ths", data_type="capital_flow") == ["ths"]
