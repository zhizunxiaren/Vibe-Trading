"""Tests for data module config (self-contained, no project imports)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.data.config import DataDownloadConfig, RateLimitConfig, _default_data_dir


# ── _default_data_dir ──────────────────────────────────────────────────


@pytest.mark.unit
def test_default_data_dir_uses_env_var(tmp_path: Path) -> None:
    """VIBE_TRADING_DATA_DIR overrides the default path."""
    with patch.dict(os.environ, {"VIBE_TRADING_DATA_DIR": str(tmp_path / "mydata")}):
        result = _default_data_dir()
    assert result == tmp_path / "mydata"
    assert result.exists()


@pytest.mark.unit
def test_default_data_dir_falls_back_to_project_root(monkeypatch) -> None:
    """Without env var and without config file, uses <project_root>/data/."""
    monkeypatch.delenv("VIBE_TRADING_DATA_DIR", raising=False)
    with patch("src.data.config._load_config_file", return_value={}):
        result = _default_data_dir()
    assert result.name == "data"
    assert "Vibe-Trading" in str(result)


# ── RateLimitConfig ────────────────────────────────────────────────────


@pytest.mark.unit
def test_rate_limit_defaults() -> None:
    cfg = RateLimitConfig()
    assert cfg.requests_per_second == 2.0
    assert cfg.burst_size == 5
    assert cfg.base_delay_seconds == 0.5
    assert cfg.max_delay_seconds == 30.0
    assert cfg.batch_size == 100
    assert cfg.batch_pause_seconds == 5.0
    assert cfg.proxy_url == ""


@pytest.mark.unit
def test_rate_limit_from_env() -> None:
    with patch.dict(os.environ, {
        "VIBE_TRADING_DATA_RPS": "3.0",
        "VIBE_TRADING_DATA_BURST": "10",
        "VIBE_TRADING_DATA_DELAY": "0.2",
        "VIBE_TRADING_DATA_MAX_DELAY": "60.0",
        "VIBE_TRADING_DATA_BATCH": "200",
        "VIBE_TRADING_DATA_BATCH_PAUSE": "10.0",
        "VIBE_TRADING_DATA_PROXY": "http://127.0.0.1:7890",
    }):
        cfg = DataDownloadConfig.from_env()
    rl = cfg.rate_limit
    assert rl.requests_per_second == 3.0
    assert rl.burst_size == 10
    assert rl.base_delay_seconds == 0.2
    assert rl.max_delay_seconds == 60.0
    assert rl.batch_size == 200
    assert rl.batch_pause_seconds == 10.0
    assert rl.proxy_url == "http://127.0.0.1:7890"


# ── DataDownloadConfig ─────────────────────────────────────────────────


@pytest.mark.unit
def test_config_from_env_defaults() -> None:
    cfg = DataDownloadConfig.from_env()
    assert cfg.db_path.suffix == ".duckdb"
    assert cfg.max_retries == 3
    assert cfg.tdx_timeout == 30
    assert len(cfg.user_agents) >= 3


@pytest.mark.unit
def test_config_db_path_env(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with patch.dict(os.environ, {"VIBE_TRADING_DATA_DB": str(db)}):
        cfg = DataDownloadConfig.from_env()
    assert cfg.db_path == db


@pytest.mark.unit
def test_config_user_agents_are_non_empty() -> None:
    cfg = DataDownloadConfig()
    assert all(len(ua) > 20 for ua in cfg.user_agents)
