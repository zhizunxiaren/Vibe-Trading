"""Self-contained configuration for the daily data downloader.

No imports from other ``agent/src/`` modules — this module is designed to be
usable as a standalone package.

Resolution order (first wins):
1. ``VIBE_TRADING_DATA_DIR`` env var
2. ``<project_root>/data-config.json`` → ``data_dir`` field
3. ``<project_root>/data/`` (default)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Project root: agent/src/data/config.py → agent/src/ → agent/ → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _PROJECT_ROOT / "data-config.json"


def _load_config_file() -> dict:
    """Load ``<project_root>/data-config.json`` if it exists."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _default_data_dir() -> Path:
    """Resolve the default data directory.

    1. ``VIBE_TRADING_DATA_DIR`` env var (absolute or relative to CWD).
    2. ``data-config.json`` → ``data_dir`` field.
    3. ``<project_root>/data/`` (built-in default).
    """
    # 1. Env var
    if env := os.getenv("VIBE_TRADING_DATA_DIR"):
        p = Path(env)
        if not p.is_absolute():
            p = Path.cwd() / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Config file
    cfg = _load_config_file()
    if cfg_dir := cfg.get("data_dir"):
        p = Path(cfg_dir)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 3. Project default
    data_dir = _PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@dataclass
class RateLimitConfig:
    """Rate-limiting parameters for HTTP-based data sources (THS, AKShare).

    TDX (mootdx TCP) is NOT rate-limited — this only applies to HTTP sources.
    """

    # ── Token bucket ──────────────────────────────────────────────────
    requests_per_second: float = 2.0       # Max sustained request rate
    burst_size: int = 5                    # Burst capacity (tokens refill at rps)

    # ── Adaptive backoff ──────────────────────────────────────────────
    base_delay_seconds: float = 0.5        # Starting delay between requests
    max_delay_seconds: float = 30.0        # Cap on backoff after repeated errors
    backoff_multiplier: float = 2.0        # Exponential factor per consecutive error

    # ── Batch pauses ──────────────────────────────────────────────────
    batch_size: int = 100                  # Requests per batch before a longer pause
    batch_pause_seconds: float = 5.0       # Pause duration between batches

    # ── Proxy ─────────────────────────────────────────────────────────
    proxy_url: str = ""                    # e.g. ``http://127.0.0.1:7890`` (from env)


@dataclass
class DataDownloadConfig:
    """Configuration for the daily market data downloader.

    All fields can be overridden via environment variables (see ``from_env()``).
    """

    # ── Storage ───────────────────────────────────────────────────────
    db_path: Path = field(default_factory=lambda: _default_data_dir() / "market_data.duckdb")

    # ── Sources ───────────────────────────────────────────────────────
    tdx_timeout: int = 30                  # mootdx TCP timeout (seconds)

    # ── Rate limiting (HTTP sources only) ─────────────────────────────
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    # ── Retry ─────────────────────────────────────────────────────────
    max_retries: int = 3                   # Max retry attempts per symbol on transient errors

    # ── User-Agent rotation ───────────────────────────────────────────
    user_agents: tuple[str, ...] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    )

    # ── env-var overrides ─────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> DataDownloadConfig:
        """Create config from environment variables with sensible defaults."""
        db_path = _default_data_dir() / "market_data.duckdb"
        if env_db := os.getenv("VIBE_TRADING_DATA_DB"):
            db_path = Path(env_db).expanduser()

        return cls(
            db_path=db_path,
            tdx_timeout=int(os.getenv("VIBE_TRADING_TDX_TIMEOUT", "30")),
            max_retries=int(os.getenv("VIBE_TRADING_DATA_RETRIES", "3")),
            rate_limit=RateLimitConfig(
                requests_per_second=float(
                    os.getenv("VIBE_TRADING_DATA_RPS", "2.0")
                ),
                burst_size=int(os.getenv("VIBE_TRADING_DATA_BURST", "5")),
                base_delay_seconds=float(
                    os.getenv("VIBE_TRADING_DATA_DELAY", "0.5")
                ),
                max_delay_seconds=float(
                    os.getenv("VIBE_TRADING_DATA_MAX_DELAY", "30.0")
                ),
                batch_size=int(os.getenv("VIBE_TRADING_DATA_BATCH", "100")),
                batch_pause_seconds=float(
                    os.getenv("VIBE_TRADING_DATA_BATCH_PAUSE", "5.0")
                ),
                proxy_url=os.getenv("VIBE_TRADING_DATA_PROXY", ""),
            ),
        )


# Module-level default config instance.
config = DataDownloadConfig.from_env()
