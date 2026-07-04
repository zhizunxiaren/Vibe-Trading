---
name: volume-ranking
category: analysis
description: Run local A-share volume ranking analytics from daily OHLCV data.
---

# Volume Ranking

Use this skill when the user asks for A-share成交量排名、放量股票、最近 N 个交易日成交量前 N 名，or a similar local daily OHLCV ranking.

## Required Tool

Use the `run_analysis` tool instead of writing ad hoc SQL.

```json
{
  "recipe_id": "top-volume",
  "params": {
    "days": 20,
    "limit": 100
  }
}
```

## Defaults

- `days`: `20`
- `limit`: `100`

These parameters answer “按照 20 个交易日的成交量排名前一百”.

## Result Handling

The tool returns a table-like analytics result with `columns`, `rows`, and `meta`.
Use `rows` for the ranked stocks and `meta.window_start` / `meta.window_end` to state the actual trading-date window.

Do not hide an empty result. If `rows` is empty, tell the user that the local DuckDB daily data is missing or incomplete and suggest running the data download workflow.
