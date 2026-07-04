"""同花顺 (THS) data source via adata HTTP multi-source fusion.

adata (https://github.com/1nchaos/adata) aggregates:
    - 东方财富 (East Money) — primary OHLCV source
    - 同花顺 (10jqka) — concepts, indices, sentiment
    - 腾讯财经 (Tencent) — real-time quotes
    - 新浪财经 (Sina) — convertible bonds

This source is **rate-limited** (HTTP). The downloader automatically applies
token-bucket + adaptive backoff when ``needs_rate_limit=True``.

Scope:
    - A-share: adata (East Money) → AKShare fallback
    - HK equity: AKShare (adata does not directly support HK daily OHLCV)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

from src.data.config import config
from src.data.rate_limiter import RateLimiter
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

_INTRADAY_PERIODS = {"5m": "5", "15m": "15", "30m": "30", "60m": "60"}


class ThsSource(BaseDataSource):
    """同花顺/东财 A-share daily OHLCV via adata + AKShare fallback.

    Automatically applies per-request delay + adaptive backoff because
    all data paths are HTTP-based.  Without this, 50+ requests fire in
    rapid succession and trigger IP bans from East Money / AKShare.
    """

    name = "ths"
    markets = {"a_share", "hk_equity"}
    needs_rate_limit = True  # HTTP — rate limiter is mandatory

    def __init__(self) -> None:
        self._session = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._consecutive_errors = 0

    def _delay(self, base_override: float = 0.0) -> None:
        """Sleep between HTTP requests to avoid IP bans.

        Args:
            base_override: If >0, use this as base instead of the config default.
        """
        base = base_override or config.rate_limit.base_delay_seconds
        if self._consecutive_errors > 0:
            backoff = base * (2 ** min(self._consecutive_errors - 1, 5))
            backoff = min(backoff, config.rate_limit.max_delay_seconds)
            time.sleep(max(base, backoff))
        else:
            time.sleep(base)

    def _on_ok(self) -> None:
        self._consecutive_errors = 0

    def _on_err(self) -> None:
        self._consecutive_errors += 1

    # ── availability ───────────────────────────────────────────────

    def is_available(self) -> bool:
        """Available if adata OR akshare is installed."""
        try:
            import adata  # noqa: F401
            return True
        except ImportError:
            pass
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    # ── symbols ────────────────────────────────────────────────────

    def fetch_symbols(self, market: str) -> list[str]:
        """Return symbols for *market* via adata or AKShare.

        The downloader typically resolves symbols externally (via AKShare
        bulk APIs), so this method returns an empty list to signal
        "caller-provided".
        """
        _ = market
        return []

    # ── daily fetch ────────────────────────────────────────────────

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV via the best available path per symbol.

        A-share: adata (East Money) → AKShare fallback.
        HK equity: AKShare.
        """
        # Split codes by market.
        a_codes = [c for c in codes if c.upper().endswith((".SH", ".SZ", ".BJ"))]
        hk_codes = [c for c in codes if c.upper().endswith(".HK")]

        result: dict[str, pd.DataFrame] = {}

        if a_codes:
            result.update(self._fetch_a_share(a_codes, start_date, end_date))
        if hk_codes:
            result.update(self._fetch_hk(hk_codes, start_date, end_date))

        return result

    # ── A-share: adata → AKShare ───────────────────────────────────

    def _fetch_a_share(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch A-share daily data: adata first, fall back to AKShare."""
        result: dict[str, pd.DataFrame] = {}

        # Try adata first (faster, better rate handling).
        try:
            import adata as ad  # noqa: F811

            for code in codes:
                symbol = _strip_suffix(code)
                self._delay()
                try:
                    df = ad.stock.market.get_market(
                        stock_code=symbol,
                        k_type=1,  # daily
                        start_date=start_date,
                        end_date=end_date,
                    )
                    normalized = self._normalize(code, df)
                    if normalized is not None:
                        result[code] = normalized
                        self._on_ok()
                except Exception as exc:
                    logger.debug("adata failed for %s: %s", code, exc)
                    self._on_err()
            if result:
                logger.info(
                    "adata: %d/%d A-share symbols fetched", len(result), len(codes),
                )
                return result
        except ImportError:
            logger.debug("adata not installed, using AKShare for A-shares")
        except Exception as exc:
            logger.warning("adata batch failed, falling back to AKShare: %s", exc)

        # Fall back to AKShare for remaining codes.
        remaining = [c for c in codes if c not in result]
        if remaining:
            logger.info("Falling back to AKShare for %d A-share symbols", len(remaining))
            result.update(self._fetch_via_akshare(remaining, start_date, end_date))

        return result

    # ── HK: AKShare ────────────────────────────────────────────────

    def _fetch_hk(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch HK equity daily data via AKShare."""
        return self._fetch_via_akshare(codes, start_date, end_date)

    # ── AKShare universal path ─────────────────────────────────────

    def _fetch_via_akshare(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV via AKShare for any market."""
        try:
            import akshare as ak
        except ImportError:
            logger.error("AKShare not installed — cannot fetch data")
            return {}

        result: dict[str, pd.DataFrame] = {}
        for code in codes:
            self._delay()
            try:
                df = self._fetch_one_akshare(ak, code, start_date, end_date)
                if df is not None:
                    result[code] = df
                    self._on_ok()
            except Exception as exc:
                logger.warning("AKShare failed for %s: %s", code, exc)
                self._on_err()
        return result

    @staticmethod
    def _fetch_one_akshare(
        ak,
        code: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single symbol via AKShare."""
        symbol = _strip_suffix(code)
        upper = code.upper()

        if upper.endswith(".HK"):
            df = ak.stock_hk_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="",
            )
        elif upper.endswith(".BJ"):
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
            # Map BJ columns (may differ slightly).
            col_map = {
                "日期": "trade_date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
            if df is not None and not df.empty:
                df = df.rename(columns=col_map)
        else:
            # Standard A-share (SH/SZ).
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )

        if df is None or df.empty:
            return None
        return ThsSource._normalize(code, df)

    # ── normalise ──────────────────────────────────────────────────

    @staticmethod
    def _normalize(code: str, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Normalise a provider DataFrame to the standard OHLCV schema."""
        if df is None or df.empty:
            return None

        # adata returns columns: stock_code, trade_date, open, high, low,
        # close, volume, turnover, change_pct, turnover_rate, ...
        # AKShare returns columns: 日期, 股票代码, 开盘, 收盘, 最高, 最低,
        # 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        col_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "turnover": "amount",
        }
        df = df.rename(columns=col_map)

        # Ensure trade_date is a DatetimeIndex.
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")
        elif df.index.name is None:
            df.index = pd.to_datetime(df.index)
        df.index.name = "trade_date"
        df = df.sort_index()

        # Coerce numeric columns.
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Ensure amount exists.
        if "amount" not in df.columns:
            df["amount"] = 0.0

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
        """Fetch intraday OHLCV via AKShare (East Money) for A-shares."""
        period = _INTRADAY_PERIODS.get(interval)
        if period is None:
            raise ValueError(
                f"THS unsupported intraday interval: {interval!r}. "
                f"Supported: {sorted(_INTRADAY_PERIODS)}"
            )
        try:
            import akshare as ak
        except ImportError:
            logger.error("AKShare not installed — cannot fetch intraday")
            return {}

        result: dict[str, pd.DataFrame] = {}
        for code in codes:
            symbol = _strip_suffix(code)
            self._delay()
            try:
                df = ak.stock_zh_a_hist_min_em(
                    symbol=symbol,
                    period=period,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )
                if df is not None and not df.empty:
                    normalized = self._normalize_intraday(code, df, fallback_date=start_date)
                    if normalized is not None:
                        normalized = normalized[
                            (normalized["trade_date"] >= str(start_date))
                            & (normalized["trade_date"] <= str(end_date))
                        ]
                    if normalized is not None and not normalized.empty:
                        result[code] = normalized
                        self._on_ok()
            except Exception as exc:
                logger.warning("intraday failed for %s: %s", code, exc)
                self._on_err()
        return result

    @staticmethod
    def _normalize_intraday(
        code: str,
        df: pd.DataFrame,
        *,
        fallback_date: str = "",
    ) -> pd.DataFrame | None:
        """Normalise AKShare intraday output to standard schema."""
        _ = code
        if df is None or df.empty:
            return None
        col_map = {
            "时间": "bar_time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        if "bar_time" in df.columns:
            raw_time = df["bar_time"].astype(str)
        else:
            raw_time = pd.Series([""] * len(df), index=df.index)

        parsed_time = pd.to_datetime(raw_time, errors="coerce")
        parsed_dates = raw_time.str.extract(r"(\d{4}[-/]\d{2}[-/]\d{2})", expand=False)
        parsed_dates = parsed_dates.str.replace("/", "-", regex=False)
        if fallback_date:
            parsed_dates = parsed_dates.fillna(str(fallback_date))
        df["trade_date"] = parsed_dates.fillna("")

        parsed_bar_times = parsed_time.dt.strftime("%H:%M")
        df["bar_time"] = parsed_bar_times.where(parsed_time.notna(), raw_time.str[-5:])
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "amount" not in df.columns:
            df["amount"] = 0.0
        keep = ["trade_date", "bar_time", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep if c in df.columns]]
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df if not df.empty else None

    # ── capital flow ────────────────────────────────────────────────

    def fetch_capital_flow(
        self,
        codes: list[str],
        trade_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch capital flow (主力资金流向) via AKShare.

        Only for A-shares. Returns one row per symbol with 主力/超大单/
        大单/中单/小单 net inflow data.
        """
        try:
            import akshare as ak
        except ImportError:
            logger.error("AKShare not installed — cannot fetch capital flow")
            return {}

        result: dict[str, pd.DataFrame] = {}
        for code in codes:
            symbol = _strip_suffix(code)
            self._delay(base_override=2.0)  # capital flow needs slower pace
            try:
                df = ak.stock_individual_fund_flow(
                    stock=symbol,
                    market="sh" if symbol.startswith("6") else "sz",
                )
                if df is None or df.empty:
                    continue
                # Filter to the requested date.
                if "日期" in df.columns:
                    df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
                    df = df[df["日期"] == trade_date]
                if df.empty:
                    continue
                normalized = self._normalize_capital_flow(code, trade_date, df)
                if normalized is not None:
                    result[code] = normalized
                    self._on_ok()
            except Exception as exc:
                logger.debug("capital flow failed for %s: %s", code, exc)
                self._on_err()
        return result

    @staticmethod
    def _normalize_capital_flow(
        code: str, trade_date: str, df: pd.DataFrame,
    ) -> pd.DataFrame | None:
        """Normalise AKShare capital flow output."""
        if df is None or df.empty:
            return None
        # Map AKShare Chinese column names.
        col_map = {
            "主力净流入-净额": "main_net_inflow",
            "主力净流入-净占比": "main_net_inflow_pct",
            "超大单净流入-净额": "super_large_net_inflow",
            "大单净流入-净额": "large_net_inflow",
            "中单净流入-净额": "medium_net_inflow",
            "小单净流入-净额": "small_net_inflow",
        }
        out = pd.DataFrame({"code": [code], "trade_date": [trade_date]})
        for cn, en in col_map.items():
            if cn in df.columns:
                out[en] = pd.to_numeric(df[cn].iloc[:1], errors="coerce").values
            else:
                out[en] = 0.0
        return out


# ── helpers ─────────────────────────────────────────────────────────────


def _strip_suffix(code: str) -> str:
    """Strip market suffix: ``600036.SH`` → ``600036``."""
    return code.split(".")[0]
