"""TDX (通达信) data source via mootdx TCP-direct protocol.

No authentication required. No per-IP rate limiting (binary protocol over TCP).

Scope: A-share OHLCV (沪/深). HK equity is NOT served by TDX — fall back to
the THS source or AKShare for HK stocks.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from src.data.config import config
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

# ── Intraday frequency codes for mootdx bars() ─────────────────────────
_INTRADAY_FREQ: dict[str, int] = {
    "15m": 1,
    "30m": 2,
    "60m": 3,
    "5m": 0,
    "1m": 8,
}
_BARS_PAGE = 800
_MAX_PAGES = 30  # ~1 year of 15m bars

# ── TDX market-to-suffix mapping ───────────────────────────────────────
_SH_SUFFIX = ".SH"
_SZ_SUFFIX = ".SZ"
_BJ_SUFFIX = ".BJ"


def _is_a_share(code: str) -> bool:
    """Accept explicit ``.SH/.SZ/.BJ`` suffix or bare 6-digit ticker."""
    upper = code.upper()
    if upper.endswith((_SH_SUFFIX, _SZ_SUFFIX, _BJ_SUFFIX)):
        return True
    return len(code) == 6 and code.isdigit()


def _is_bj(code: str) -> bool:
    """Detect 北交所 symbols. Mootdx std factory does not serve BJ data."""
    upper = code.upper()
    if upper.endswith(_BJ_SUFFIX):
        return True
    return len(code) == 6 and code.isdigit() and code[0] in ("4", "8")


def _to_tdx_symbol(code: str) -> str:
    """Strip suffix for mootdx (e.g. ``600036.SH`` → ``600036``)."""
    return code.split(".")[0]


# ── TDX Source ─────────────────────────────────────────────────────────


class TdxSource(BaseDataSource):
    """通达信 A-share daily OHLCV via mootdx TCP-direct protocol.

    Uses ``mootdx.quotes.Quotes.get_k_data()`` for daily data which supports
    native date-range queries — no pagination needed.
    """

    name = "tdx"
    markets = {"a_share"}
    needs_rate_limit = False  # TCP protocol, no HTTP rate limiting needed

    def __init__(self, timeout: int | None = None) -> None:
        self._client = None
        self._timeout = timeout or config.tdx_timeout

    # ── availability ───────────────────────────────────────────────

    def is_available(self) -> bool:
        """Available if mootdx is installed."""
        try:
            import mootdx  # noqa: F401
            return True
        except ImportError:
            return False

    # ── client factory ─────────────────────────────────────────────

    def _get_client(self):
        """Lazy-init the mootdx Quotes client."""
        if self._client is None:
            from mootdx.quotes import Quotes

            self._client = Quotes.factory(
                market="std",
                timeout=self._timeout,
                bestip=True,
            )
        return self._client

    # ── symbols ────────────────────────────────────────────────────

    def fetch_symbols(self, market: str) -> list[str]:
        """Return A-share symbols from mootdx stock list.

        Mootdx does not expose a full symbol list API, so we return an
        empty list to signal "caller should provide symbols".  The
        downloader injects symbols from its own universe resolver.
        """
        _ = market
        return []  # Caller resolves symbols externally.

    # ── daily fetch ────────────────────────────────────────────────

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV for *codes* over a date range.

        Uses ``get_k_data()`` which natively accepts start/end dates.
        Non-A-share and 北交所 codes are silently skipped.
        """
        client = self._get_client()
        result: dict[str, pd.DataFrame] = {}

        for code in codes:
            if not _is_a_share(code):
                logger.debug("tdx: skipping non-A-share %s", code)
                continue
            if _is_bj(code):
                logger.debug("tdx: skipping BJ %s (not supported)", code)
                continue

            try:
                df = self._fetch_one(client, code, start_date, end_date)
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("tdx: failed for %s: %s", code, exc)

        return result

    def _fetch_one(
        self,
        client,
        code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily data for a single symbol."""
        symbol = _to_tdx_symbol(code)
        df = client.get_k_data(
            code=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        if df is None or df.empty:
            return None

        # Normalise column names.
        col_map = {
            "date": "trade_date",
            "vol": "volume",
        }
        df = df.rename(columns=col_map)
        df["amount"] = df.get("amount", 0.0)

        # Set trade_date index.
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")
        elif df.index.name is None:
            df.index = pd.to_datetime(df.index)
        df.index.name = "trade_date"
        df = df.sort_index()

        # Coerce numeric.
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep = ["open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df if not df.empty else None

    # ── intraday fetch ──────────────────────────────────────────────

    def fetch_intraday_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "15m",
    ) -> dict[str, pd.DataFrame]:
        """Fetch intraday OHLCV via mootdx ``bars()`` pagination.

        Uses offset-based pagination to walk backward through history.
        Not all TDX servers serve historical intraday data for all
        symbols — older dates may return empty.
        """
        if interval not in _INTRADAY_FREQ:
            raise ValueError(
                f"TDX unsupported intraday interval: {interval!r}. "
                f"Supported: {sorted(_INTRADAY_FREQ)}"
            )
        freq = _INTRADAY_FREQ[interval]
        client = self._get_client()
        result: dict[str, pd.DataFrame] = {}

        start_ts = pd.Timestamp(start_date)
        for code in codes:
            if not _is_a_share(code) or _is_bj(code):
                continue
            symbol = _to_tdx_symbol(code)
            try:
                df = self._fetch_bars_paginated(
                    client, symbol, freq, start_ts, end_date, interval,
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("tdx intraday failed for %s: %s", code, exc)
        return result

    @staticmethod
    def _fetch_bars_paginated(
        client,
        symbol: str,
        freq: int,
        start_ts: pd.Timestamp,
        end_date: str,
        interval: str,
    ) -> Optional[pd.DataFrame]:
        """Walk backward through bars() pages until ``start_ts`` is covered."""
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        chunks: list[pd.DataFrame] = []

        for page in range(_MAX_PAGES):
            df = client.bars(
                symbol=symbol,
                frequency=freq,
                start=page * _BARS_PAGE,
                offset=_BARS_PAGE,
            )
            if df is None or df.empty:
                break
            chunks.append(df)
            first_dt = pd.to_datetime(df["datetime"].iloc[0])
            if first_dt <= start_ts:
                break

        if not chunks:
            return None
        combined = pd.concat(chunks, ignore_index=False)

        # Normalise columns.
        if "datetime" in combined.columns:
            combined["datetime"] = pd.to_datetime(combined["datetime"])
            combined["trade_date"] = combined["datetime"].dt.strftime("%Y-%m-%d")
            combined["bar_time"] = combined["datetime"].dt.strftime("%H:%M")
        col_map = {"vol": "volume"}
        combined = combined.rename(columns=col_map)
        if "amount" not in combined.columns:
            combined["amount"] = 0.0

        # Clip date range.
        combined = combined[
            (combined["datetime"] >= start_ts) & (combined["datetime"] < end_ts)
        ]

        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in combined.columns:
                combined[col] = pd.to_numeric(combined[col], errors="coerce")

        keep = ["trade_date", "bar_time", "open", "high", "low", "close", "volume", "amount"]
        out = combined[[c for c in keep if c in combined.columns]]
        out = out.dropna(subset=["open", "high", "low", "close"])
        return out.sort_values(["trade_date", "bar_time"]) if not out.empty else None

    # ── capital flow ────────────────────────────────────────────────

    def fetch_capital_flow(
        self,
        codes: list[str],
        trade_date: str,
    ) -> dict[str, pd.DataFrame]:
        """TDX does not serve capital flow data. Returns empty."""
        _ = codes, trade_date
        return {}
