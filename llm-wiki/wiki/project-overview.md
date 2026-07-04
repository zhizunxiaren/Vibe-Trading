# Project Overview

Vibe-Trading is a local finance research workspace with an agent backend, a Vite/React frontend, market data downloaders, DuckDB storage, and analysis/backtest workflows.

The local daily market database is configured through `data-config.json`. In this checkout it points to `I:\Alpha\trading-data`, where `market_data.duckdb` stores tables such as `daily_ohlcv`, `intraday_ohlcv`, `capital_flow`, `stock_info`, and `download_log`.

For wiki-backed project knowledge, keep immutable source files in `llm-wiki/raw/` and maintain derived markdown pages in `llm-wiki/wiki/`.
