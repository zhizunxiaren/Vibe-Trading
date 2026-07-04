"""DuckDB storage for daily + intraday market data and capital flow.

DuckDB is an embedded columnar analytical database — 10-50× faster than
SQLite for time-series OLAP queries. Zero-config, no server process,
already a project dependency (``duckdb>=1.2.0`` in pyproject.toml).

Schema
------
``stock_info`` — symbol master data.
``daily_ohlcv`` — daily OHLCV, ``(code, trade_date)`` compound PK.
``intraday_ohlcv`` — 15m/30m/60m OHLCV, ``(code, trade_date, bar_time)`` PK.
``capital_flow`` — daily capital flow (主力流向), ``(code, trade_date)`` PK.
``download_log`` — audit trail of every download run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from src.data.config import config

logger = logging.getLogger(__name__)

# ── DDL ────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_info (
    code              VARCHAR NOT NULL,
    name              VARCHAR,
    market            VARCHAR NOT NULL,    -- SH / SZ / BJ / HK
    exchange          VARCHAR,             -- SSE / SZSE / BSE / HKEX
    float_market_cap  DOUBLE,              -- 流通市值 (元)
    total_market_cap  DOUBLE,              -- 总市值 (元)
    float_shares      DOUBLE,              -- 流通股本 (股)
    source            VARCHAR,
    updated_at        VARCHAR,
    PRIMARY KEY (code, market)
);

CREATE TABLE IF NOT EXISTS daily_ohlcv (
    code        VARCHAR NOT NULL,
    trade_date  DATE NOT NULL,        -- YYYY-MM-DD
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    amount      DOUBLE,
    source      VARCHAR,              -- tdx / ths / akshare
    fetched_at  TIMESTAMP,            -- ISO-8601 timestamp of when this row was fetched
    PRIMARY KEY (code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_date ON daily_ohlcv(trade_date);
CREATE INDEX IF NOT EXISTS idx_daily_ohlcv_code ON daily_ohlcv(code);

CREATE TABLE IF NOT EXISTS intraday_ohlcv (
    code        VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,          -- 5m / 15m / 30m / 60m
    trade_date  DATE NOT NULL,          -- YYYY-MM-DD
    bar_time    TIME NOT NULL,          -- HH:MM (e.g. 09:45, 10:00)
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    amount      DOUBLE,
    source      VARCHAR,                -- tdx / ths / akshare
    fetched_at  TIMESTAMP,
    PRIMARY KEY (code, interval, trade_date, bar_time)
);

CREATE INDEX IF NOT EXISTS idx_intraday_code_date ON intraday_ohlcv(code, trade_date);

CREATE TABLE IF NOT EXISTS capital_flow (
    code                   VARCHAR NOT NULL,
    trade_date             DATE NOT NULL,       -- YYYY-MM-DD
    main_net_inflow        DOUBLE,              -- 主力净流入 (万元)
    main_net_inflow_pct    DOUBLE,              -- 主力净流入占比 (%)
    super_large_net_inflow  DOUBLE,              -- 超大单净流入
    large_net_inflow       DOUBLE,              -- 大单净流入
    medium_net_inflow      DOUBLE,              -- 中单净流入
    small_net_inflow       DOUBLE,              -- 小单净流入
    source                 VARCHAR,              -- ths / akshare
    fetched_at             TIMESTAMP,
    PRIMARY KEY (code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_capital_flow_date ON capital_flow(trade_date);

CREATE SEQUENCE IF NOT EXISTS seq_download_log_id START 1;

CREATE TABLE IF NOT EXISTS download_log (
    id              BIGINT PRIMARY KEY DEFAULT nextval('seq_download_log_id'),
    market          VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    start_date      VARCHAR NOT NULL,
    end_date        VARCHAR NOT NULL,
    status          VARCHAR NOT NULL,    -- ok / partial / failed / running
    symbols_total   BIGINT DEFAULT 0,
    symbols_ok      BIGINT DEFAULT 0,
    symbols_failed  BIGINT DEFAULT 0,
    rows_inserted   BIGINT DEFAULT 0,
    error_msg       VARCHAR,
    started_at      VARCHAR NOT NULL,
    finished_at     VARCHAR
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Storage ─────────────────────────────────────────────────────────────


class Storage:
    """DuckDB-backed daily market data store.

    Args:
        db_path: Path to the DuckDB file. Defaults to the path in
            :class:`DataDownloadConfig`.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else config.db_path
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    # ── connection management ──────────────────────────────────────

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(self.db_path))
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self._migrate_legacy_intraday_interval()
        self.conn.execute(_SCHEMA_SQL)

    def _migrate_legacy_intraday_interval(self) -> None:
        """Rebuild legacy intraday tables whose PK lacked ``interval``."""
        exists = self.conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name='intraday_ohlcv'"
        ).fetchone()
        if not exists or int(exists[0]) == 0:
            return

        columns = self.conn.execute("PRAGMA table_info('intraday_ohlcv')").fetchall()
        if any(str(row[1]) == "interval" for row in columns):
            return

        self.conn.execute("DROP INDEX IF EXISTS idx_intraday_code_date")
        self.conn.execute("ALTER TABLE intraday_ohlcv RENAME TO intraday_ohlcv_legacy")
        self.conn.execute(
            """
            CREATE TABLE intraday_ohlcv (
                code        VARCHAR NOT NULL,
                interval    VARCHAR NOT NULL,
                trade_date  DATE NOT NULL,
                bar_time    TIME NOT NULL,
                open        DOUBLE,
                high        DOUBLE,
                low         DOUBLE,
                close       DOUBLE,
                volume      DOUBLE,
                amount      DOUBLE,
                source      VARCHAR,
                fetched_at  TIMESTAMP,
                PRIMARY KEY (code, interval, trade_date, bar_time)
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO intraday_ohlcv
                (code, interval, trade_date, bar_time, open, high, low, close, volume, amount, source, fetched_at)
            SELECT code, '15m', trade_date, bar_time, open, high, low, close, volume, amount, source, fetched_at
            FROM intraday_ohlcv_legacy
            """
        )
        self.conn.execute("DROP TABLE intraday_ohlcv_legacy")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── row counting helper ────────────────────────────────────────

    def _count_table(self, table: str) -> int:
        row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    # ── stock info ─────────────────────────────────────────────────

    def upsert_stock_info(
        self, records: list[dict[str, str]]
    ) -> int:
        """Insert or update stock master records.

        Args:
            records: List of dicts with keys: code, name, market, source.

        Returns:
            Number of rows affected.
        """
        sql = """
            INSERT OR REPLACE INTO stock_info
                (code, name, market, exchange, float_market_cap, total_market_cap, float_shares, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = _now_iso()
        rows = [
            (
                r["code"],
                r.get("name", ""),
                r["market"],
                r.get("exchange", ""),
                float(r.get("float_market_cap", 0) or 0),
                float(r.get("total_market_cap", 0) or 0),
                float(r.get("float_shares", 0) or 0),
                r.get("source", ""),
                now,
            )
            for r in records
        ]
        before = self._count_table("stock_info")
        self.conn.executemany(sql, rows)
        after = self._count_table("stock_info")
        return max(0, after - before)

    # ── daily OHLCV ────────────────────────────────────────────────

    def upsert_daily(
        self,
        df: pd.DataFrame,
        *,
        source: str = "",
    ) -> int:
        """Insert or replace daily OHLCV rows.

        Args:
            df: DataFrame with columns ``[code, trade_date, open, high, low,
                close, volume, amount]``. ``trade_date`` may be the index or a
                column.
            source: Label written into the ``source`` column.

        Returns:
            Number of rows written.
        """
        if df is None or df.empty:
            return 0

        # Ensure trade_date is a column, not just the index.
        work = df.copy()
        if "trade_date" not in work.columns:
            work["trade_date"] = work.index.astype(str)

        fetched_at = _now_iso()
        sql = """
            INSERT OR REPLACE INTO daily_ohlcv
                (code, trade_date, open, high, low, close, volume, amount, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        records: list[tuple] = []
        for _, row in work.iterrows():
            records.append((
                str(row.get("code", "")),
                str(row.get("trade_date", "")),
                float(row.get("open", 0.0) or 0.0),
                float(row.get("high", 0.0) or 0.0),
                float(row.get("low", 0.0) or 0.0),
                float(row.get("close", 0.0) or 0.0),
                float(row.get("volume", 0.0) or 0.0),
                float(row.get("amount", 0.0) or 0.0),
                source,
                fetched_at,
            ))

        try:
            self.conn.executemany(sql, records)
        except Exception as exc:
            logger.error("upsert_daily failed: %s", exc)
            raise
        return len(records)

    # ── intraday OHLCV ──────────────────────────────────────────────

    def upsert_intraday(
        self,
        df: pd.DataFrame,
        *,
        source: str = "",
        interval: str = "15m",
    ) -> int:
        """Insert or replace intraday OHLCV rows.

        Args:
            df: DataFrame with columns ``[code, trade_date, bar_time,
                open, high, low, close, volume, amount]``.
            source: Label written into the ``source`` column.

        Returns:
            Number of rows written.
        """
        if df is None or df.empty:
            return 0

        work = df.copy()
        for col in ("trade_date", "bar_time"):
            if col not in work.columns:
                work[col] = work.index.astype(str) if col == "trade_date" else ""
        if "interval" not in work.columns:
            work["interval"] = interval or "15m"

        fetched_at = _now_iso()
        sql = """
            INSERT OR REPLACE INTO intraday_ohlcv
                (code, interval, trade_date, bar_time, open, high, low, close, volume, amount, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        records: list[tuple] = []
        for _, row in work.iterrows():
            interval_value = row.get("interval", interval or "15m")
            if pd.isna(interval_value) or not str(interval_value).strip():
                interval_value = interval or "15m"
            records.append((
                str(row.get("code", "")),
                str(interval_value),
                str(row.get("trade_date", "")),
                str(row.get("bar_time", "")),
                float(row.get("open", 0.0) or 0.0),
                float(row.get("high", 0.0) or 0.0),
                float(row.get("low", 0.0) or 0.0),
                float(row.get("close", 0.0) or 0.0),
                float(row.get("volume", 0.0) or 0.0),
                float(row.get("amount", 0.0) or 0.0),
                source,
                fetched_at,
            ))

        try:
            self.conn.executemany(sql, records)
        except Exception as exc:
            logger.error("upsert_intraday failed: %s", exc)
            raise
        return len(records)

    def read_intraday(
        self,
        codes: list[str],
        start_date: str = "",
        end_date: str = "",
        interval: str = "",
    ) -> pd.DataFrame:
        """Read stored intraday OHLCV."""
        if not codes:
            return pd.DataFrame()
        placeholders = ",".join("?" for _ in codes)
        sql = f"SELECT * FROM intraday_ohlcv WHERE code IN ({placeholders})"
        params: list[str] = list(codes)
        if interval:
            sql += " AND interval = ?"; params.append(interval)
        if start_date:
            sql += " AND trade_date >= ?"; params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"; params.append(end_date)
        sql += " ORDER BY code, interval, trade_date, bar_time"
        return self.conn.execute(sql, params).df()

    # ── capital flow ───────────────────────────────────────────────

    def upsert_capital_flow(
        self,
        df: pd.DataFrame,
        *,
        source: str = "",
    ) -> int:
        """Insert or replace capital flow rows.

        Args:
            df: DataFrame with columns ``[code, trade_date, main_net_inflow,
                main_net_inflow_pct, super_large_net_inflow, large_net_inflow,
                medium_net_inflow, small_net_inflow]``.
            source: Label written into the ``source`` column.

        Returns:
            Number of rows written.
        """
        if df is None or df.empty:
            return 0

        work = df.copy()
        if "trade_date" not in work.columns:
            work["trade_date"] = work.index.astype(str)

        fetched_at = _now_iso()
        sql = """
            INSERT OR REPLACE INTO capital_flow
                (code, trade_date, main_net_inflow, main_net_inflow_pct,
                 super_large_net_inflow, large_net_inflow, medium_net_inflow,
                 small_net_inflow, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        fields = [
            "main_net_inflow", "main_net_inflow_pct",
            "super_large_net_inflow", "large_net_inflow",
            "medium_net_inflow", "small_net_inflow",
        ]
        records: list[tuple] = []
        for _, row in work.iterrows():
            vals = [float(row.get(f, 0.0) or 0.0) for f in fields]
            records.append((
                str(row.get("code", "")),
                str(row.get("trade_date", "")),
                *vals,
                source,
                fetched_at,
            ))

        try:
            self.conn.executemany(sql, records)
        except Exception as exc:
            logger.error("upsert_capital_flow failed: %s", exc)
            raise
        return len(records)

    def read_capital_flow(
        self,
        codes: list[str],
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Read stored capital flow."""
        if not codes:
            return pd.DataFrame()
        placeholders = ",".join("?" for _ in codes)
        sql = f"SELECT * FROM capital_flow WHERE code IN ({placeholders})"
        params: list[str] = list(codes)
        if start_date:
            sql += " AND trade_date >= ?"; params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"; params.append(end_date)
        sql += " ORDER BY code, trade_date"
        return self.conn.execute(sql, params).df()

    # ── date queries ───────────────────────────────────────────────

    def get_latest_date(self, market: str) -> Optional[str]:
        """Return the most recent trade_date stored for *market*.

        Market is inferred from the code suffix:
        ``.SH`` / ``.SZ`` / ``.BJ`` → a_share, ``.HK`` → hk_equity.

        Args:
            market: Market key (``a_share``, ``hk_equity``).

        Returns:
            Latest date as ``YYYY-MM-DD``, or ``None`` if the table is empty.
        """
        _suffixes: dict[str, list[str]] = {
            "a_share": [".SH", ".SZ", ".BJ"],
            "hk_equity": [".HK"],
        }
        suffixes = _suffixes.get(market, [])
        if not suffixes:
            return None

        clauses = " OR ".join(["d.code LIKE ?"] * len(suffixes))
        query = f"SELECT MAX(d.trade_date) FROM daily_ohlcv d WHERE {clauses}"
        params = [f"%{s}" for s in suffixes]
        row = self.conn.execute(query, params).fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None

    def get_latest_date_per_code(
        self, codes: list[str]
    ) -> dict[str, str]:
        """Return the latest trade_date for each code.

        Returns:
            Mapping ``{code: YYYY-MM-DD}``. Codes with no data are absent.
        """
        if not codes:
            return {}
        placeholders = ",".join("?" for _ in codes)
        rows = self.conn.execute(
            f"SELECT code, MAX(trade_date) FROM daily_ohlcv WHERE code IN ({placeholders}) GROUP BY code",
            codes,
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows if row[1] is not None}

    # ── download log ───────────────────────────────────────────────

    def log_start(
        self,
        market: str,
        source: str,
        start_date: str,
        end_date: str,
        symbols_total: int,
    ) -> int:
        """Record the start of a download run. Returns the log row id."""
        row = self.conn.execute(
            """INSERT INTO download_log
               (market, source, start_date, end_date, status, symbols_total, started_at)
               VALUES (?, ?, ?, ?, 'running', ?, ?)
               RETURNING id""",
            (market, source, start_date, end_date, symbols_total, _now_iso()),
        ).fetchone()
        return int(row[0]) if row else 0

    def log_finish(
        self,
        log_id: int,
        *,
        status: str,
        symbols_ok: int = 0,
        symbols_failed: int = 0,
        rows_inserted: int = 0,
        error_msg: str = "",
    ) -> None:
        """Update a download log row with completion data."""
        self.conn.execute(
            """UPDATE download_log
               SET status = ?, symbols_ok = ?, symbols_failed = ?,
                   rows_inserted = ?, error_msg = ?, finished_at = ?
               WHERE id = ?""",
            (status, symbols_ok, symbols_failed, rows_inserted, error_msg or "", _now_iso(), log_id),
        )

    # ── read-back ──────────────────────────────────────────────────

    def read_daily(
        self,
        codes: list[str],
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Read stored daily OHLCV for analysis.

        Args:
            codes: List of symbol codes.
            start_date: Optional YYYY-MM-DD lower bound.
            end_date: Optional YYYY-MM-DD upper bound.

        Returns:
            DataFrame with index ``trade_date`` and columns
            ``[code, open, high, low, close, volume, amount]``.
        """
        if not codes:
            return pd.DataFrame()

        placeholders = ",".join("?" for _ in codes)
        sql = f"SELECT * FROM daily_ohlcv WHERE code IN ({placeholders})"
        params: list[str] = list(codes)

        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        sql += " ORDER BY code, trade_date"

        df = self.conn.execute(sql, params).df()
        if not df.empty and "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")
        return df

    # ── stats ──────────────────────────────────────────────────────

    @property
    def row_count(self) -> int:
        """Total rows in daily_ohlcv."""
        return self._count_table("daily_ohlcv")
