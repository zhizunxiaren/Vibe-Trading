"""Daily market data downloader for A-share and HK equity.

Self-contained module — no imports from other ``agent/src/`` packages.
Configured entirely via environment variables (see :class:`DataDownloadConfig`).

Sources:
    - **tdx**: 通达信 via mootdx (TCP direct, no auth, no rate limit).
    - **tdx_offline**: 通达信 VIP daily ZIP cache for bulk daily A-share pulls.
    - **tencent**: Tencent Finance quote/K-line HTTP APIs for safe daily and
      intraday A-share pulls.
    - **ths**: 同花顺/东财 via adata + AKShare fallback (HTTP, rate-limited).

Storage:
    DuckDB database at ``VIBE_TRADING_DATA_DIR/market_data.duckdb``
    (defaults to ``<project_root>/data/market_data.duckdb``).

Usage::

    from src.data import Downloader, get_downloader

    dl = get_downloader(source="tdx")
    result = dl.run(market="a_share")
    print(f"Downloaded {result.symbols_ok}/{result.symbols_total} symbols")

Environment variables::

    VIBE_TRADING_DATA_DIR       Data directory (default: <project_root>/data)
    VIBE_TRADING_DATA_DB        DuckDB path (default: <data_dir>/market_data.duckdb)
    VIBE_TRADING_DATA_PROXY     HTTP proxy URL for THS source
    VIBE_TRADING_DATA_RPS       Max requests/second for HTTP (default: 2.0)
    VIBE_TRADING_DATA_DELAY     Base delay between requests (default: 0.5s)
    VIBE_TRADING_DATA_MAX_DELAY Max backoff delay (default: 30.0s)
    VIBE_TRADING_DATA_BATCH     Symbols per batch before pause (default: 100)
    VIBE_TRADING_DATA_BATCH_PAUSE  Pause between batches in seconds (default: 5.0)
    VIBE_TRADING_TDX_TIMEOUT    mootdx TCP timeout in seconds (default: 30)
"""

from src.data.config import DataDownloadConfig, RateLimitConfig, config
from src.data.downloader import DownloadResult, Downloader, get_downloader
from src.data.rate_limiter import RateLimiter
from src.data.storage import Storage
from src.data.universe import latest_trade_date, resolve_symbols

__all__ = [
    "DataDownloadConfig",
    "Downloader",
    "DownloadResult",
    "RateLimitConfig",
    "RateLimiter",
    "Storage",
    "config",
    "get_downloader",
    "latest_trade_date",
    "resolve_symbols",
]
