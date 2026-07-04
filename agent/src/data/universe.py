"""Market universe and trade-date helpers for data downloads."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)


def latest_trade_date(today: date | None = None) -> str:
    """Return the most recent trade date as ``YYYY-MM-DD``.

    This simple helper treats weekends as non-trading days and moves them
    back to Friday. Holiday calendars are intentionally left to providers.
    """
    current = today or date.today()
    if current.weekday() >= 5:
        current -= timedelta(days=current.weekday() - 4)
    return current.strftime("%Y-%m-%d")


def resolve_a_share_symbols() -> list[str]:
    """Return the A-share universe using AKShare or a static fallback."""
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        codes: list[str] = []
        for _, row in df.iterrows():
            code = str(row.get("code", ""))
            if not code or len(code) != 6:
                continue
            if code.startswith("6"):
                codes.append(f"{code}.SH")
            elif code.startswith(("0", "3")):
                codes.append(f"{code}.SZ")
            elif code.startswith(("4", "8")):
                codes.append(f"{code}.BJ")
        if codes:
            logger.info("Resolved %d A-share symbols via AKShare", len(codes))
            return codes
    except Exception as exc:
        logger.warning("Failed to resolve A-share symbols via AKShare: %s", exc)

    logger.warning("Using fallback A-share symbol list (沪深300)")
    try:
        import akshare as ak

        df = ak.index_stock_cons_weight_csindex(symbol="000300")
        return [
            f"{str(row['成分券代码'])}.SH"
            if str(row["成分券代码"]).startswith("6")
            else f"{str(row['成分券代码'])}.SZ"
            for _, row in df.iterrows()
        ]
    except Exception:
        return []


def resolve_hk_symbols() -> list[str]:
    """Return the HK equity universe using AKShare."""
    try:
        import akshare as ak

        df = ak.stock_hk_spot_em()
        codes = [
            f"{str(row.get('代码', '')).zfill(5)}.HK"
            for _, row in df.iterrows()
            if str(row.get("代码", "")).strip()
        ]
        if codes:
            logger.info("Resolved %d HK symbols via AKShare", len(codes))
            return codes
    except Exception as exc:
        logger.warning("Failed to resolve HK symbols via AKShare: %s", exc)
    return []


UNIVERSE_RESOLVERS: dict[str, Callable[[], list[str]]] = {
    "a_share": resolve_a_share_symbols,
    "hk_equity": resolve_hk_symbols,
}


def resolve_symbols(market: str, source: BaseDataSource | None = None) -> list[str]:
    """Resolve the full symbol universe for *market*.

    Built-in market resolvers are preferred because several source adapters
    intentionally return an empty symbol list. Unknown markets fall back to
    the source adapter if one was supplied.
    """
    resolver = UNIVERSE_RESOLVERS.get(market)
    if resolver is not None:
        return resolver()
    if source is not None:
        return source.fetch_symbols(market)
    return []
