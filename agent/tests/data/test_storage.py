"""Tests for DuckDB storage layer."""

from __future__ import annotations

import pandas as pd
import pytest
import duckdb

from src.data.storage import Storage


@pytest.fixture
def storage() -> Storage:
    """Return a fresh in-memory DuckDB-backed Storage."""
    return Storage(db_path=":memory:")


# ── Schema ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_schema_creates_tables(storage: Storage) -> None:
    """All expected tables exist after first connection."""
    rows = storage.conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    table_names = {r[0] for r in rows}
    assert "stock_info" in table_names
    assert "daily_ohlcv" in table_names
    assert "download_log" in table_names


@pytest.mark.unit
def test_daily_ohlcv_has_compound_pk(storage: Storage) -> None:
    """(code, trade_date) is the primary key."""
    rows = storage.conn.execute(
        "SELECT constraint_type FROM information_schema.table_constraints "
        "WHERE table_name='daily_ohlcv' AND constraint_type='PRIMARY KEY'"
    ).fetchall()
    assert len(rows) >= 1


@pytest.mark.unit
def test_duckdb_connection_is_established(storage: Storage) -> None:
    """DuckDB connects and responds to basic queries."""
    row = storage.conn.execute("SELECT 1 AS one").fetchone()
    assert row[0] == 1


# ── Upsert stock_info ───────────────────────────────────────────────────


@pytest.mark.unit
def test_upsert_stock_info(storage: Storage) -> None:
    records = [
        {
            "code": "600036.SH", "name": "招商银行", "market": "SH",
            "exchange": "SSE", "float_market_cap": 8e11, "total_market_cap": 1e12,
            "float_shares": 2.06e10, "source": "akshare",
        },
        {
            "code": "00700.HK", "name": "腾讯控股", "market": "HK",
            "exchange": "HKEX", "float_market_cap": 0, "total_market_cap": 0,
            "float_shares": 0, "source": "ths",
        },
    ]
    n = storage.upsert_stock_info(records)
    assert n >= 2

    row = storage.conn.execute(
        "SELECT name, market, exchange, float_market_cap FROM stock_info WHERE code='600036.SH'"
    ).fetchone()
    assert row[0] == "招商银行"
    assert float(row[3]) == 8e11


# ── Upsert daily OHLCV ──────────────────────────────────────────────────


@pytest.mark.unit
def test_upsert_daily_inserts_rows(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH", "600036.SH"],
        "trade_date": ["2026-06-09", "2026-06-10"],
        "open": [35.0, 35.5],
        "high": [36.0, 36.2],
        "low": [34.8, 35.0],
        "close": [35.8, 35.9],
        "volume": [1e7, 1.2e7],
        "amount": [3.5e8, 4.2e8],
    })
    n = storage.upsert_daily(df, source="tdx")
    assert n == 2


@pytest.mark.unit
def test_upsert_daily_replaces_duplicates(storage: Storage) -> None:
    """A later fetch for the same bar should refresh provider-corrected data."""
    df = pd.DataFrame({
        "code": ["000001.SZ"],
        "trade_date": ["2026-06-09"],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "close": [10.2],
        "volume": [5e6],
        "amount": [5e7],
    })
    n1 = storage.upsert_daily(df, source="tdx")
    assert n1 == 1

    refreshed = df.copy()
    refreshed["close"] = [10.8]
    refreshed["amount"] = [6e7]
    n2 = storage.upsert_daily(refreshed, source="ths")
    assert n2 == 1

    row = storage.conn.execute(
        "SELECT close, amount, source FROM daily_ohlcv WHERE code='000001.SZ' AND trade_date='2026-06-09'"
    ).fetchone()
    assert row == (10.8, 6e7, "ths")
    assert storage.row_count == 1


@pytest.mark.unit
def test_upsert_daily_empty_df(storage: Storage) -> None:
    assert storage.upsert_daily(pd.DataFrame(), source="tdx") == 0


# ── get_latest_date ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_latest_date_empty(storage: Storage) -> None:
    assert storage.get_latest_date("a_share") is None


@pytest.mark.unit
def test_get_latest_date_returns_max(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH", "600036.SH", "000001.SZ"],
        "trade_date": ["2026-06-08", "2026-06-09", "2026-06-07"],
        "open": [35.0, 35.5, 10.0],
        "high": [36.0, 36.2, 10.5],
        "low": [34.8, 35.0, 9.8],
        "close": [35.8, 35.9, 10.2],
        "volume": [1e7, 1.2e7, 5e6],
        "amount": [3.5e8, 4.2e8, 5e7],
    })
    storage.upsert_daily(df, source="tdx")
    assert storage.get_latest_date("a_share") == "2026-06-09"


@pytest.mark.unit
def test_get_latest_date_hk(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["00700.HK"],
        "trade_date": ["2026-06-05"],
        "open": [380.0],
        "high": [385.0],
        "low": [378.0],
        "close": [382.0],
        "volume": [1e7],
        "amount": [3.8e9],
    })
    storage.upsert_daily(df, source="ths")
    assert storage.get_latest_date("hk_equity") == "2026-06-05"


# ── get_latest_date_per_code ────────────────────────────────────────────


@pytest.mark.unit
def test_get_latest_date_per_code(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH", "000001.SZ"],
        "trade_date": ["2026-06-09", "2026-06-07"],
        "open": [35.0, 10.0],
        "high": [36.0, 10.5],
        "low": [34.8, 9.8],
        "close": [35.8, 10.2],
        "volume": [1e7, 5e6],
        "amount": [3.5e8, 5e7],
    })
    storage.upsert_daily(df, source="tdx")

    dates = storage.get_latest_date_per_code(["600036.SH", "000001.SZ", "000002.SZ"])
    assert dates["600036.SH"] == "2026-06-09"
    assert dates["000001.SZ"] == "2026-06-07"
    assert "000002.SZ" not in dates


# ── Download log ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_log_start_and_finish(storage: Storage) -> None:
    log_id = storage.log_start(
        market="a_share", source="tdx",
        start_date="2026-06-01", end_date="2026-06-09",
        symbols_total=5000,
    )
    assert log_id > 0

    storage.log_finish(
        log_id, status="ok", symbols_ok=4998, symbols_failed=2,
        rows_inserted=24990,
    )

    row = storage.conn.execute(
        "SELECT status, symbols_total, symbols_ok, symbols_failed, rows_inserted "
        "FROM download_log WHERE id=?",
        (log_id,),
    ).fetchone()
    assert row == ("ok", 5000, 4998, 2, 24990)


# ── read_daily ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_read_daily_returns_dataframe(storage: Storage) -> None:
    df_in = pd.DataFrame({
        "code": ["600036.SH", "600036.SH"],
        "trade_date": ["2026-06-08", "2026-06-09"],
        "open": [35.0, 35.5],
        "high": [36.0, 36.2],
        "low": [34.8, 35.0],
        "close": [35.8, 35.9],
        "volume": [1e7, 1.2e7],
        "amount": [3.5e8, 4.2e8],
    })
    storage.upsert_daily(df_in, source="tdx")

    df_out = storage.read_daily(["600036.SH"], start_date="2026-06-09")
    assert len(df_out) >= 1


# ── row_count ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_row_count(storage: Storage) -> None:
    assert storage.row_count == 0
    df = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-09"],
        "open": [35.0], "high": [36.0], "low": [34.8], "close": [35.8],
        "volume": [1e7], "amount": [3.5e8],
    })
    storage.upsert_daily(df, source="tdx")
    assert storage.row_count == 1


# ── Context manager ─────────────────────────────────────────────────────


# ── Intraday OHLCV ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_intraday_schema_has_table(storage: Storage) -> None:
    rows = storage.conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name='intraday_ohlcv'"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.unit
def test_init_schema_migrates_legacy_intraday_table_to_interval_pk() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE intraday_ohlcv (
            code        VARCHAR NOT NULL,
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
            PRIMARY KEY (code, trade_date, bar_time)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO intraday_ohlcv
            (code, trade_date, bar_time, open, high, low, close, volume, amount, source, fetched_at)
        VALUES ('600036.SH', '2026-06-12', '10:00', 35.0, 35.2, 34.9, 35.1, 500000, 17500000, 'legacy', now())
        """
    )
    conn.execute("CREATE INDEX idx_intraday_code_date ON intraday_ohlcv(code, trade_date)")
    storage = Storage(db_path=":memory:")
    storage._conn = conn

    storage._init_schema()
    storage.upsert_intraday(pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "bar_time": ["10:00"],
        "open": [35.0],
        "high": [35.8],
        "low": [34.9],
        "close": [35.7],
        "volume": [600000],
        "amount": [21000000],
    }), source="tencent", interval="60m")

    rows = storage.conn.execute(
        "SELECT interval, close FROM intraday_ohlcv ORDER BY interval"
    ).fetchall()
    assert rows == [("15m", 35.1), ("60m", 35.7)]


@pytest.mark.unit
def test_upsert_intraday_inserts_rows(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH", "600036.SH"],
        "trade_date": ["2026-06-12", "2026-06-12"],
        "bar_time": ["09:45", "10:00"],
        "open": [35.0, 35.1],
        "high": [35.2, 35.3],
        "low": [34.9, 35.0],
        "close": [35.1, 35.2],
        "volume": [5e5, 6e5],
        "amount": [1.75e7, 2.1e7],
    })
    n = storage.upsert_intraday(df, source="tdx")
    assert n == 2


@pytest.mark.unit
def test_upsert_intraday_replaces_duplicate_interval_bar(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "bar_time": ["09:45"],
        "open": [35.0], "high": [35.2], "low": [34.9], "close": [35.1],
        "volume": [5e5], "amount": [1.75e7],
    })
    n1 = storage.upsert_intraday(df, source="tdx")
    refreshed = df.copy()
    refreshed["close"] = [35.4]
    n2 = storage.upsert_intraday(refreshed, source="tencent", interval="15m")
    assert n1 == 1
    assert n2 == 1

    row = storage.conn.execute(
        "SELECT close, source FROM intraday_ohlcv "
        "WHERE code='600036.SH' AND interval='15m' AND trade_date='2026-06-12' AND bar_time='09:45'"
    ).fetchone()
    assert row == (35.4, "tencent")


@pytest.mark.unit
def test_upsert_intraday_keeps_intervals_separate(storage: Storage) -> None:
    base = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "bar_time": ["10:00"],
        "open": [35.0], "high": [35.2], "low": [34.9], "close": [35.1],
        "volume": [5e5], "amount": [1.75e7],
    })
    storage.upsert_intraday(base, source="tencent", interval="15m")
    hourly = base.copy()
    hourly["close"] = [35.8]
    storage.upsert_intraday(hourly, source="tencent", interval="60m")

    all_rows = storage.read_intraday(["600036.SH"], start_date="2026-06-12")
    assert len(all_rows) == 2
    m15 = storage.read_intraday(["600036.SH"], start_date="2026-06-12", interval="15m")
    h60 = storage.read_intraday(["600036.SH"], start_date="2026-06-12", interval="60m")
    assert float(m15.iloc[0]["close"]) == 35.1
    assert float(h60.iloc[0]["close"]) == 35.8


@pytest.mark.unit
def test_read_intraday(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "bar_time": ["10:00"],
        "open": [35.1], "high": [35.3], "low": [35.0], "close": [35.2],
        "volume": [6e5], "amount": [2.1e7],
    })
    storage.upsert_intraday(df, source="tdx")
    out = storage.read_intraday(["600036.SH"], start_date="2026-06-12")
    assert len(out) >= 1


# ── Capital flow ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_capital_flow_schema_has_table(storage: Storage) -> None:
    rows = storage.conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name='capital_flow'"
    ).fetchall()
    assert len(rows) == 1


@pytest.mark.unit
def test_upsert_capital_flow_inserts_rows(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "main_net_inflow": [5000.0],
        "main_net_inflow_pct": [3.5],
        "super_large_net_inflow": [3000.0],
        "large_net_inflow": [2000.0],
        "medium_net_inflow": [-500.0],
        "small_net_inflow": [-4500.0],
    })
    n = storage.upsert_capital_flow(df, source="ths")
    assert n == 1


@pytest.mark.unit
def test_upsert_capital_flow_replaces_duplicates(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["000001.SZ"],
        "trade_date": ["2026-06-12"],
        "main_net_inflow": [8000.0],
        "main_net_inflow_pct": [5.0],
        "super_large_net_inflow": [5000.0],
        "large_net_inflow": [3000.0],
        "medium_net_inflow": [0.0],
        "small_net_inflow": [-8000.0],
    })
    n1 = storage.upsert_capital_flow(df, source="ths")
    refreshed = df.copy()
    refreshed["main_net_inflow"] = [9000.0]
    n2 = storage.upsert_capital_flow(refreshed, source="ths")
    assert n1 == 1
    assert n2 == 1

    row = storage.conn.execute(
        "SELECT main_net_inflow FROM capital_flow WHERE code='000001.SZ' AND trade_date='2026-06-12'"
    ).fetchone()
    assert row == (9000.0,)


@pytest.mark.unit
def test_read_capital_flow(storage: Storage) -> None:
    df = pd.DataFrame({
        "code": ["600036.SH"],
        "trade_date": ["2026-06-12"],
        "main_net_inflow": [5000.0],
        "main_net_inflow_pct": [3.5],
        "super_large_net_inflow": [3000.0],
        "large_net_inflow": [2000.0],
        "medium_net_inflow": [-500.0],
        "small_net_inflow": [-4500.0],
    })
    storage.upsert_capital_flow(df, source="ths")
    out = storage.read_capital_flow(["600036.SH"])
    assert len(out) >= 1
    assert float(out.iloc[0]["main_net_inflow"]) == 5000.0


@pytest.mark.unit
def test_context_manager_closes_connection() -> None:
    with Storage(db_path=":memory:") as s:
        s.upsert_daily(pd.DataFrame({
            "code": ["000001.SZ"], "trade_date": ["2026-06-09"],
            "open": [10.0], "high": [10.5], "low": [9.8], "close": [10.2],
            "volume": [1e6], "amount": [1e7],
        }), source="tdx")
    assert s._conn is None
