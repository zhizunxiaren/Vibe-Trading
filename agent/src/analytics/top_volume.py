"""Top-volume ranking recipe for local A-share daily OHLCV data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.analytics.models import AnalysisRecipe, AnalyticsColumn, AnalyticsError


TOP_VOLUME_COLUMNS = (
    AnalyticsColumn("rank", "Rank", "integer", "right"),
    AnalyticsColumn("code", "Code"),
    AnalyticsColumn("name", "Name"),
    AnalyticsColumn("total_volume", "Total Volume", "number", "right"),
    AnalyticsColumn("total_amount", "Total Amount", "number", "right"),
    AnalyticsColumn("float_market_cap", "Float Market Cap", "number", "right"),
    AnalyticsColumn("trade_days", "Trade Days", "integer", "right"),
    AnalyticsColumn("window_start", "Window Start", "date"),
    AnalyticsColumn("window_end", "Window End", "date"),
)


def _as_int(params: dict[str, Any], key: str, *, minimum: int, maximum: int) -> int:
    raw = params[key]
    if isinstance(raw, bool):
        raise AnalyticsError(f"{key} must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError(f"{key} must be an integer") from exc
    if value < minimum or value > maximum:
        raise AnalyticsError(f"{key} must be between {minimum} and {maximum}")
    return value


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def run_top_volume(conn: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Rank stocks by total volume over the latest N trading dates."""
    days = _as_int(params, "days", minimum=1, maximum=120)
    limit = _as_int(params, "limit", minimum=1, maximum=200)
    effective_params = {"days": days, "limit": limit}

    date_rows = conn.execute(
        """SELECT DISTINCT trade_date
           FROM daily_ohlcv
           WHERE code LIKE '%.SH' OR code LIKE '%.SZ' OR code LIKE '%.BJ'
           ORDER BY trade_date DESC
           LIMIT ?""",
        (days,),
    ).fetchall()
    window_dates = [_iso(row[0]) for row in date_rows if row]
    window_dates = [value for value in window_dates if value is not None]
    window_start = min(window_dates) if window_dates else None
    window_end = max(window_dates) if window_dates else None
    trade_days = len(window_dates)

    rows = conn.execute(
        """WITH recent_dates AS (
               SELECT DISTINCT trade_date
               FROM daily_ohlcv
               WHERE code LIKE '%.SH' OR code LIKE '%.SZ' OR code LIKE '%.BJ'
               ORDER BY trade_date DESC
               LIMIT ?
           )
           SELECT d.code,
                  COALESCE(s.name, d.code) AS name,
                  SUM(d.volume) AS total_volume,
                  SUM(d.amount) AS total_amount,
                  COALESCE(s.float_market_cap, 0) AS float_market_cap,
                  COUNT(DISTINCT d.trade_date) AS trade_days
           FROM daily_ohlcv d
           LEFT JOIN stock_info s ON d.code = s.code
           WHERE d.trade_date IN (SELECT trade_date FROM recent_dates)
           GROUP BY d.code, s.name, s.float_market_cap
           HAVING trade_days = (SELECT COUNT(*) FROM recent_dates)
           ORDER BY total_volume DESC, d.code
           LIMIT ?""",
        (days, limit),
    ).fetchall()

    result_rows = []
    for rank, row in enumerate(rows, start=1):
        result_rows.append(
            {
                "rank": rank,
                "code": str(row[0]),
                "name": str(row[1]),
                "total_volume": float(row[2] or 0),
                "total_amount": float(row[3] or 0),
                "float_market_cap": float(row[4] or 0),
                "trade_days": int(row[5] or 0),
                "window_start": window_start,
                "window_end": window_end,
            }
        )

    return {
        "id": TOP_VOLUME_RECIPE.id,
        "title": TOP_VOLUME_RECIPE.title,
        "description": TOP_VOLUME_RECIPE.description,
        "params": effective_params,
        "columns": [column.to_dict() for column in TOP_VOLUME_COLUMNS],
        "rows": result_rows,
        "meta": {
            "trade_days": trade_days,
            "window_start": window_start,
            "window_end": window_end,
        },
    }


TOP_VOLUME_RECIPE = AnalysisRecipe(
    id="top-volume",
    title="Top Volume",
    description="Rank A-share stocks by total traded volume over the latest N trading days.",
    default_params={"days": 20, "limit": 100},
    columns=TOP_VOLUME_COLUMNS,
    runner=run_top_volume,
)
