"""DuckDB connection helpers for local analytics."""

from __future__ import annotations


def connect_market_db():
    """Open the configured market database in read-only mode."""
    import duckdb
    from src.data.config import config as data_config

    return duckdb.connect(str(data_config.db_path), read_only=True)
