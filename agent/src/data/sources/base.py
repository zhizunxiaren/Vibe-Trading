"""Abstract base for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class DataSource(Protocol):
    """Protocol that every market data source must satisfy.

    Each source wraps a specific data provider (TDX, THS, etc.) and
    normalises output to a consistent OHLCV schema.
    """

    name: str
    markets: set[str]  # e.g. {"a_share", "hk_equity"}
    needs_rate_limit: bool  # True for HTTP sources (THS), False for TCP (TDX)

    def is_available(self) -> bool:
        """Check whether this data source is usable (deps installed, etc.)."""
        ...

    def fetch_symbols(self, market: str) -> list[str]:
        """Return the list of tradeable symbols for *market*.

        Args:
            market: Market key, e.g. ``"a_share"`` or ``"hk_equity"``.

        Returns:
            List of symbol codes in standard format (e.g. ``600036.SH``).
        """
        ...

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV for *codes* over a date range.

        Args:
            codes: Symbol list.
            start_date: YYYY-MM-DD (inclusive).
            end_date: YYYY-MM-DD (inclusive).

        Returns:
            Mapping ``{code: DataFrame(trade_date, open, high, low, close, volume, amount)}``.
        """
        ...

    def fetch_intraday_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "15m",
    ) -> dict[str, pd.DataFrame]:
        """Fetch intraday OHLCV for *codes* over a date range.

        Args:
            codes: Symbol list.
            start_date: YYYY-MM-DD (inclusive).
            end_date: YYYY-MM-DD (inclusive).
            interval: Bar width — ``15m``, ``30m``, or ``60m``.

        Returns:
            Mapping ``{code: DataFrame(trade_date, bar_time, open, high, low, close, volume, amount)}``.
        """
        ...

    def fetch_capital_flow(
        self,
        codes: list[str],
        trade_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch capital flow for *codes* on a single trade date.

        Args:
            codes: Symbol list.
            trade_date: YYYY-MM-DD.

        Returns:
            Mapping ``{code: DataFrame(main_net_inflow, ...)}``.
        """
        ...


class BaseDataSource(ABC):
    """Abstract base class with shared helpers for data sources."""

    name: str = ""
    markets: set[str] = set()

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch_symbols(self, market: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    @staticmethod
    def _normalize_ohlcv(
        df: pd.DataFrame,
        *,
        col_map: dict[str, str] | None = None,
    ) -> pd.DataFrame | None:
        """Normalise a DataFrame to the standard OHLCV+amount schema.

        Args:
            df: Raw DataFrame from the data provider.
            col_map: Optional mapping from provider column names to standard
                names: ``open, high, low, close, volume, amount``.

        Returns:
            Normalised DataFrame with columns ``[trade_date, open, high, low,
            close, volume, amount]`` and a ``trade_date`` DateTimeIndex, or
            ``None`` if the input is empty.
        """
        if df is None or df.empty:
            return None

        _default_map = {
            "vol": "volume",
        }
        effective_map = {**col_map, **_default_map} if col_map else _default_map
        out = df.rename(columns=effective_map).copy()

        # Ensure trade_date is a DatetimeIndex.
        if "trade_date" not in out.columns:
            if out.index.name == "trade_date" or out.index.name is None:
                out.index = pd.to_datetime(out.index)
                out.index.name = "trade_date"
        else:
            out["trade_date"] = pd.to_datetime(out["trade_date"])
            out = out.set_index("trade_date")

        out.index.name = "trade_date"
        out = out.sort_index()

        # Coerce numeric columns.
        for col in ("open", "high", "low", "close", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        # Add amount column if missing.
        if "amount" not in out.columns:
            out["amount"] = 0.0

        keep = ["open", "high", "low", "close", "volume", "amount"]
        out = out[[c for c in keep if c in out.columns]]
        out = out.dropna(subset=["open", "high", "low", "close"])
        return out if not out.empty else None
