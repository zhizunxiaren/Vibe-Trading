"""TDX offline data source — download VIP daily data ZIP and parse ``.day`` files.

Downloads ``http://data.tdx.com.cn/vipdoc/hsjday.zip`` (free, official),
caches it locally (re-download if older than 1 day), extracts the ``.day``
binary files, and parses them with mootdx Reader.

Full A-share market in one ZIP — no per-symbol HTTP requests, no IP-ban risk.
"""

from __future__ import annotations

import logging
import struct
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

from src.data.config import config
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

# Official TDX VIP daily data ZIP.
_TDX_VIP_URL = "http://data.tdx.com.cn/vipdoc/hsjday.zip"
# Local cache directory.
_CACHE_DIR = Path(config.db_path).parent / "tdx_cache"
_CACHE_ZIP = _CACHE_DIR / "hsjday.zip"
# Re-download if ZIP is older than this (seconds).
# 4 hours — within a session reuse cache, next day always re-download.
_CACHE_MAX_AGE = 4 * 3600


class TdxOfflineSource(BaseDataSource):
    """TDX offline daily OHLCV via VIP data ZIP download + mootdx Reader.

    Caches the ZIP locally.  Only re-downloads if older than 24 hours.
    Full A-share market — no per-symbol requests, no IP bans.
    """

    name = "tdx_offline"
    markets = {"a_share"}
    needs_rate_limit = False

    def is_available(self) -> bool:
        return True  # Pure Python, no deps needed

    def fetch_symbols(self, market: str) -> list[str]:
        _ = market
        return []

    # ── daily fetch ────────────────────────────────────────────────

    def fetch_daily_range(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict[str, pd.DataFrame]:
        """Download/cache ZIP, extract, parse ``.day`` files with mootdx Reader."""
        result: dict[str, pd.DataFrame] = {}

        a_codes = [c for c in codes if c.upper().endswith((".SH", ".SZ"))]
        if not a_codes:
            return result

        needed: set[str] = {
            c.split(".")[0] for c in a_codes
            if c.split(".")[0].isdigit() and len(c.split(".")[0]) == 6
        }
        if not needed:
            return result

        # ── Download (with cache) ──────────────────────────────────
        zip_path = self._ensure_zip()
        if zip_path is None:
            return result

        with tempfile.TemporaryDirectory(prefix="tdx_parse_") as tmp:
            extract_dir = Path(tmp) / "vipdoc"
            extract_dir.mkdir()
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
            except Exception as exc:
                logger.error("Failed to extract ZIP: %s", exc)
                return result

            for symbol in sorted(needed):
                try:
                    df = _read_day_file(extract_dir, symbol, start_date, end_date)
                    if df is not None:
                        market = ".SH" if symbol.startswith("6") else ".SZ"
                        result[f"{symbol}{market}"] = df
                except Exception:
                    pass

        logger.info("tdx_offline: parsed %d symbols", len(result))
        return result

    # ── ZIP cache ──────────────────────────────────────────────────

    @staticmethod
    def _ensure_zip() -> Optional[Path]:
        """Return path to cached ZIP, downloading if needed."""
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Check if cache is fresh enough.
        if _CACHE_ZIP.exists():
            age = time.time() - _CACHE_ZIP.stat().st_mtime
            if age < _CACHE_MAX_AGE and _CACHE_ZIP.stat().st_size > 1_000_000:
                logger.info("Using cached ZIP (%.0f min old, %.1f MB)",
                            age / 60, _CACHE_ZIP.stat().st_size / 1e6)
                return _CACHE_ZIP

        # Download.
        logger.info("Downloading TDX VIP ZIP (%s)...", _TDX_VIP_URL)
        try:
            req = urllib.request.Request(_TDX_VIP_URL, headers={
                "User-Agent": config.user_agents[0],
            })
            resp = urllib.request.urlopen(req, timeout=300)
            data = resp.read()
            _CACHE_ZIP.write_bytes(data)
            logger.info("Downloaded: %.1f MB → %s", len(data) / 1e6, _CACHE_ZIP)
            return _CACHE_ZIP
        except Exception as exc:
            logger.error("Failed to download TDX ZIP: %s", exc)
            # Return stale cache if available as fallback.
            if _CACHE_ZIP.exists():
                logger.warning("Using stale cached ZIP as fallback")
                return _CACHE_ZIP
            return None


# ── Native .day file parser ────────────────────────────────────────────


def _read_day_file(
    extract_dir: Path,
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """Parse a TDX ``.day`` binary file directly (no mootdx needed).

    Format: 32 bytes per record —
        date(i4), open(i4×100), high(i4×100), low(i4×100), close(i4×100),
        amount(f4), volume(i4), reserved(i4)
    """
    # Determine market directory.
    if symbol.startswith("6"):
        day_file = extract_dir / "sh" / "lday" / f"sh{symbol}.day"
    else:
        day_file = extract_dir / "sz" / "lday" / f"sz{symbol}.day"

    if not day_file.exists():
        return None

    raw = day_file.read_bytes()
    records: list[dict] = []

    for i in range(0, len(raw) - 31, 32):
        try:
            date_i, open_i, high_i, low_i, close_i, amount, vol, _ = (
                struct.unpack("IIIIIfII", raw[i : i + 32])
            )
            y, m, d = date_i // 10000, (date_i % 10000) // 100, date_i % 100
            if y < 2000 or y > 2100:
                continue
            trade_date = f"{y}-{m:02d}-{d:02d}"
            if trade_date < start_date or trade_date > end_date:
                continue
            records.append({
                "trade_date": trade_date,
                "open": open_i / 100.0,
                "high": high_i / 100.0,
                "low": low_i / 100.0,
                "close": close_i / 100.0,
                "volume": float(vol),
                "amount": float(amount),
            })
        except struct.error:
            continue

    if not records:
        return None

    df = pd.DataFrame(records)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date").sort_index()
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"])
