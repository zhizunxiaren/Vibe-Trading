"""Tencent Finance data source — HTTP APIs, never IP-banned.

Two endpoints, both confirmed safe for bulk use:

- **Quote** ``qt.gtimg.cn/q=sh600036,sz000001,...`` — 88 fields: name, PE, PB,
  market cap, turnover rate, real-time price.  Batch up to ~50 symbols/request.
- **K-line** ``web.ifzq.gtimg.cn/appstock/app/fqkline/get`` — daily OHLCV with
  date range, 前复权 (qfq) by default.  One request per symbol, but no rate
  limit — safe for full-market pulls.

No auth, no API key, no per-IP throttling.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from typing import Optional

import pandas as pd

from src.data.config import config
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

_QUOTE_URL = "http://qt.gtimg.cn/q={codes}"
_KLINE_URL = (
    "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param={prefix}{symbol},day,{start},,{limit},qfq"
)
_INTRADAY_URL = (
    "http://ifzq.gtimg.cn/appstock/app/kline/mkline"
    "?param={prefix}{symbol},m{minute},,{limit}"
)
_UA = config.user_agents[0]

# Tencent intraday interval mapping.
_INTERVAL_MINUTES = {"15m": 15, "30m": 30, "60m": 60, "5m": 5}


class TencentSource(BaseDataSource):
    """Tencent Finance — quote + K-line, never IP-banned in practice.

    Uses the same APIs that QQ/WeChat stock mini-programs hit — Tencent
    has no incentive to rate-limit their own frontend traffic.
    """

    name = "tencent"
    markets = {"a_share"}
    needs_rate_limit = False  # No rate limiting needed

    def is_available(self) -> bool:
        return True  # Pure stdlib HTTP, always available

    # ── symbols ────────────────────────────────────────────────────

    def fetch_symbols(self, market: str) -> list[str]:
        _ = market
        return []

    # ── stock info (quote API) ─────────────────────────────────────

    def fetch_stock_info(self, codes: list[str]) -> list[dict]:
        """Pull name, PE, PB, market cap via quote API (single batch).

        Args:
            codes: List of symbols like ``["600036.SH", "000001.SZ"]``.

        Returns:
            List of dicts with keys: code, name, market, exchange,
            float_market_cap, total_market_cap, pe, pb.
        """
        results: list[dict] = []
        for i in range(0, len(codes), 50):
            batch = codes[i : i + 50]
            raw = self._fetch_quote_batch(batch)
            results.extend(raw)
            if i + 50 < len(codes):
                time.sleep(0.05)  # Tiny courtesy delay
        return results

    def _fetch_quote_batch(self, codes: list[str]) -> list[dict]:
        """Fetch one batch of quotes (≤50 symbols)."""
        # Map to Tencent format: 600036.SH → sh600036
        q_codes = []
        for c in codes:
            symbol = c.split(".")[0]
            if c.endswith(".SH"):
                q_codes.append(f"sh{symbol}")
            elif c.endswith(".SZ"):
                q_codes.append(f"sz{symbol}")
            elif c.endswith(".BJ"):
                q_codes.append(f"bj{symbol}")

        if not q_codes:
            return []

        url = _QUOTE_URL.format(codes=",".join(q_codes))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            resp = urllib.request.urlopen(req, timeout=15)
            raw = resp.read().decode("gbk", errors="replace")
        except Exception as exc:
            logger.warning("tencent quote API failed: %s", exc)
            return []

        results: list[dict] = []
        for line in raw.strip().split("\n"):
            line = line.strip().rstrip(";")
            if not line or "=" not in line:
                continue
            try:
                _, val = line.split("=", 1)
                val = val.strip('"').strip("'")
                fields = val.split("~")
                if len(fields) < 47:
                    continue

                name = fields[1]
                symbol = fields[2]
                if not symbol or not name:
                    continue

                market = "SH" if fields[0] == "1" else ("BJ" if symbol.startswith(("4", "8")) else "SZ")
                code = f"{symbol}.{market}"

                results.append({
                    "code": code,
                    "name": name,
                    "market": market,
                    "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market, ""),
                    "float_market_cap": _to_float(fields[44]) * 1e8 if len(fields) > 44 else 0,  # 亿→元
                    "total_market_cap": _to_float(fields[45]) * 1e8 if len(fields) > 45 else 0,
                    "pe": _to_float(fields[39]),
                    "pb": _to_float(fields[46]) if len(fields) > 46 else 0,
                })
            except (ValueError, IndexError):
                continue
        return results

    # ── daily K-line ───────────────────────────────────────────────

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch daily OHLCV via Tencent K-line API (前复权)."""
        result: dict[str, pd.DataFrame] = {}
        # Calculate limit: days in range + buffer
        days = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 10, 30)

        for code in codes:
            symbol = code.split(".")[0]
            upper = code.upper()
            if upper.endswith(".SH"):
                prefix = "sh"
            elif upper.endswith(".SZ"):
                prefix = "sz"
            elif upper.endswith(".BJ"):
                prefix = "bj"
            else:
                continue

            url = _KLINE_URL.format(prefix=prefix, symbol=symbol, start=start_date, limit=days)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                resp = urllib.request.urlopen(req, timeout=15)
                data = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                logger.debug("tencent K-line failed for %s: %s", code, exc)
                continue

            try:
                stock = data.get("data", {}).get(f"{prefix}{symbol}", {})
                bars = stock.get("qfqday") or stock.get("day") or []
                if not bars:
                    continue
                df = _parse_kline_bars(bars, start_date, end_date)
                if df is not None:
                    result[code] = df
            except Exception as exc:
                logger.debug("tencent parse failed for %s: %s", code, exc)

        return result

    # ── intraday K-line ─────────────────────────────────────────────

    def fetch_intraday_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "15m",
    ) -> dict[str, pd.DataFrame]:
        """Fetch intraday OHLCV via Tencent minute K-line (永不封IP)."""
        minute = _INTERVAL_MINUTES.get(interval, 15)
        result: dict[str, pd.DataFrame] = {}
        days = max((pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 5, 5)
        limit = days * (240 // minute) + 50  # bars per day × days + buffer

        for code in codes:
            prefix, symbol = _tencent_prefix(code)
            if not prefix:
                continue

            url = _INTRADAY_URL.format(prefix=prefix, symbol=symbol, minute=minute, limit=limit)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": _UA})
                resp = urllib.request.urlopen(req, timeout=15)
                data = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                logger.debug("tencent intraday failed for %s: %s", code, exc)
                continue

            try:
                stock = data.get("data", {}).get(f"{prefix}{symbol}", {})
                bars = stock.get(f"m{minute}", [])
                if not bars:
                    continue
                df = _parse_intraday_bars(bars, start_date, end_date)
                if df is not None:
                    result[code] = df
            except Exception as exc:
                logger.debug("tencent intraday parse failed for %s: %s", code, exc)

        return result


# ── parse helpers ───────────────────────────────────────────────────────


def _tencent_prefix(code: str) -> tuple[str, str]:
    """600036.SH → ('sh', '600036')."""
    symbol = code.split(".")[0]
    upper = code.upper()
    if upper.endswith(".SH"):
        return "sh", symbol
    elif upper.endswith(".SZ"):
        return "sz", symbol
    elif upper.endswith(".BJ"):
        return "bj", symbol
    return "", ""


def _to_float(val: str) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _parse_intraday_bars(
    bars: list,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """Parse Tencent minute K-line: [datetime, open, close, high, low, volume, {}, amount]."""
    if not bars:
        return None
    records = []
    for bar in bars:
        if len(bar) < 6:
            continue
        dt = str(bar[0])
        if dt.isdigit() and len(dt) in (12, 14):
            fmt = "%Y%m%d%H%M" if len(dt) == 12 else "%Y%m%d%H%M%S"
            parsed_dt = pd.to_datetime(dt, format=fmt, errors="coerce")
        else:
            parsed_dt = pd.to_datetime(dt, errors="coerce")
        if pd.isna(parsed_dt):
            continue

        trade_date = parsed_dt.strftime("%Y-%m-%d")
        bar_time = parsed_dt.strftime("%H:%M")
        records.append({
            "trade_date": trade_date,
            "bar_time": bar_time,
            "open": float(bar[1]),
            "close": float(bar[2]),
            "high": float(bar[3]),
            "low": float(bar[4]),
            "volume": float(bar[5]),
            "amount": float(bar[7]) * 1e4 if len(bar) > 7 and bar[7] else 0.0,
        })

    if not records:
        return None
    df = pd.DataFrame(records)
    df = df[
        (df["trade_date"] >= str(start_date)) & (df["trade_date"] <= str(end_date))
    ]
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]) if not df.empty else None


def _parse_kline_bars(
    bars: list[list[str]],
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """Convert Tencent K-line format to standard OHLCV DataFrame.

    Each bar: ``[date, open, close, high, low, volume]``.
    """
    if not bars:
        return None

    records = []
    for bar in bars:
        if len(bar) < 6:
            continue
        records.append({
            "trade_date": bar[0],
            "open": float(bar[1]),
            "close": float(bar[2]),
            "high": float(bar[3]),
            "low": float(bar[4]),
            "volume": float(bar[5]),
            "amount": 0.0,  # Tencent K-line doesn't include amount
        })

    if not records:
        return None

    df = pd.DataFrame(records)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()

    # Clip to requested range.
    df = df.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]

    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna(subset=["open", "high", "low", "close"]) if not df.empty else None
