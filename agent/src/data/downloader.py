"""Core downloader: orchestrates source → storage pipeline for daily market data.

Handles two very different data paths:

- **TDX (mootdx TCP)**: No rate limiting — binary protocol, ~5000 symbols in ~8 min.
- **THS (adata HTTP)**: Token-bucket rate limiter + adaptive backoff + batch pauses.
  Full A-share market (~5000 symbols) takes ~40-80 min depending on rate limits.

Design goal: never get IP-banned, even when pulling full market data.

Usage::

    from src.data import Downloader, get_downloader

    dl = get_downloader(source="tdx")
    result = dl.run(market="a_share")
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from src.data.config import config
from src.data.rate_limiter import RateLimiter
from src.data.sources.base import BaseDataSource
from src.data.sources.registry import create_source, fallback_chain
from src.data.storage import Storage
from src.data.universe import latest_trade_date, resolve_symbols

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Outcome of a single download run.

    Attributes:
        market: Market key that was downloaded.
        source: Data source name.
        start_date: Requested start date.
        end_date: Requested end date.
        status: ``ok``, ``partial``, or ``failed``.
        symbols_total: Total symbols attempted.
        symbols_ok: Symbols with at least one row inserted.
        symbols_failed: Symbols that errored out.
        rows_inserted: Total OHLCV rows written to storage.
        elapsed_seconds: Wall-clock duration of the run.
        log_id: Row id in the ``download_log`` table.
        error_msg: If status is ``failed``, the terminal error.
    """

    market: str
    source: str
    start_date: str
    end_date: str
    status: str = "ok"
    symbols_total: int = 0
    symbols_ok: int = 0
    symbols_failed: int = 0
    rows_inserted: int = 0
    elapsed_seconds: float = 0.0
    log_id: int = 0
    error_msg: str = ""


FrameWriter = Callable[[pd.DataFrame], int]


def _write_symbol_frames(
    batch: list[str],
    batch_data: dict[str, pd.DataFrame],
    write_frame: FrameWriter,
    *,
    label: str,
) -> tuple[int, int, int]:
    """Write fetched frames for one batch and return ``ok, failed, rows``."""
    ok_count = 0
    fail_count = 0
    rows_inserted = 0
    for code in batch:
        df = batch_data.get(code)
        if df is None or df.empty:
            fail_count += 1
            continue
        work = df.copy()
        work["code"] = code
        try:
            written = write_frame(work)
            if written > 0:
                ok_count += 1
                rows_inserted += written
            else:
                fail_count += 1
        except Exception as exc:
            logger.warning("%s upsert failed for %s: %s", label, code, exc)
            fail_count += 1
    return ok_count, fail_count, rows_inserted


def _finish_result(
    result: DownloadResult,
    *,
    t0: float,
    symbols_ok: int,
    symbols_failed: int,
    rows_inserted: int,
    failed_message: str,
) -> DownloadResult:
    """Populate terminal counters and status for a completed run."""
    result.symbols_ok = symbols_ok
    result.symbols_failed = symbols_failed
    result.rows_inserted = rows_inserted
    result.elapsed_seconds = time.monotonic() - t0

    if symbols_failed == 0:
        result.status = "ok"
    elif symbols_ok > 0:
        result.status = "partial"
    else:
        result.status = "failed"
        result.error_msg = failed_message
    return result


# ── Downloader ──────────────────────────────────────────────────────────


class Downloader:
    """Orchestrate daily market data fetch → storage pipeline.

    Args:
        source: A :class:`BaseDataSource` instance.
        storage: A :class:`Storage` instance.
        rate_limiter: A :class:`RateLimiter` for HTTP sources. If ``None``
            and the source needs rate limiting, one is auto-created from
            the module-level config.
    """

    def __init__(
        self,
        source: BaseDataSource,
        storage: Storage | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.source = source
        self.storage = storage or Storage()
        self.rate_limiter = rate_limiter
        if self.source.needs_rate_limit and self.rate_limiter is None:
            self.rate_limiter = RateLimiter()

    # ── main entry point ───────────────────────────────────────────

    def run(
        self,
        market: str,
        *,
        start_date: str = "",
        end_date: str = "",
        symbols: list[str] | None = None,
        dry_run: bool = False,
    ) -> DownloadResult:
        """Download daily OHLCV for *market* and upsert into storage.

        Args:
            market: Market key (``a_share``, ``hk_equity``).
            start_date: YYYY-MM-DD. If empty, uses the day after the latest
                stored date (incremental mode). Falls back to 365 days ago
                if storage is empty.
            end_date: YYYY-MM-DD. Defaults to the latest trade date.
            symbols: Optional explicit symbol list. If ``None``, resolves
                the full universe for *market*.
            dry_run: If ``True``, resolves symbols and computes the date
                window but does NOT fetch or write any data.

        Returns:
            :class:`DownloadResult` summarising the run.
        """
        t0 = time.monotonic()

        # ── 1. Resolve end date + symbols ───────────────────────────
        explicit_start_date = bool(start_date)
        if not end_date:
            end_date = latest_trade_date()

        if symbols is None:
            symbols = resolve_symbols(market, self.source)

        if not symbols:
            return DownloadResult(
                market=market,
                source=self.source.name,
                start_date=start_date,
                end_date=end_date,
                status="failed",
                error_msg=f"No symbols resolved for market {market}",
            )

        # ── 2. Resolve per-symbol date windows ──────────────────────
        symbol_groups: dict[str, list[str]] = {}
        if explicit_start_date:
            symbol_groups[start_date] = symbols
        else:
            fallback_start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
            end_ts = pd.Timestamp(end_date)
            latest_map = self.storage.get_latest_date_per_code(symbols)
            for code in symbols:
                latest = latest_map.get(code)
                symbol_start = (
                    pd.Timestamp(latest) + pd.Timedelta(days=1)
                    if latest
                    else pd.Timestamp(fallback_start)
                )
                if symbol_start > end_ts:
                    continue
                symbol_groups.setdefault(symbol_start.strftime("%Y-%m-%d"), []).append(code)

            start_date = min(symbol_groups) if symbol_groups else end_date

        result = DownloadResult(
            market=market,
            source=self.source.name,
            start_date=start_date,
            end_date=end_date,
            symbols_total=len(symbols),
        )

        if dry_run:
            result.status = "ok"
            result.elapsed_seconds = time.monotonic() - t0
            logger.info(
                "[dry-run] %s/%s: %d symbols, %s → %s",
                market, self.source.name, len(symbols), start_date, end_date,
            )
            return result

        skipped_count = len(symbols) - sum(len(group) for group in symbol_groups.values())
        if not symbol_groups:
            result.status = "ok"
            result.symbols_ok = skipped_count
            result.elapsed_seconds = time.monotonic() - t0
            logger.info("%s/%s: all %d symbols up to date", market, self.source.name, len(symbols))
            return result

        # ── 3. Log start ────────────────────────────────────────────
        result.log_id = self.storage.log_start(
            market=market,
            source=self.source.name,
            start_date=start_date,
            end_date=end_date,
            symbols_total=len(symbols),
        )

        # ── 4. Batch fetch + upsert ─────────────────────────────────
        total_inserted = 0
        ok_count = skipped_count
        fail_count = 0
        batch_size = config.rate_limit.batch_size if self.rate_limiter else 200

        processed_count = skipped_count
        for group_start, group_symbols in sorted(symbol_groups.items()):
            for i in range(0, len(group_symbols), batch_size):
                batch = group_symbols[i : i + batch_size]
                batch_end = min(i + batch_size, len(group_symbols))

                try:
                    batch_data = self.source.fetch_daily_range(
                        batch, group_start, end_date,
                    )
                except Exception as exc:
                    logger.error("Batch %d-%d failed: %s", i, batch_end - 1, exc)
                    fail_count += len(batch)
                    processed_count += len(batch)
                    if self.rate_limiter:
                        self.rate_limiter.on_error(exc)
                    continue
                batch_data = batch_data or {}

                batch_ok, batch_failed, batch_rows = _write_symbol_frames(
                    batch,
                    batch_data,
                    lambda frame: self.storage.upsert_daily(frame, source=self.source.name),
                    label="daily",
                )
                ok_count += batch_ok
                fail_count += batch_failed
                total_inserted += batch_rows

                processed_count += len(batch)

                if self.rate_limiter:
                    self.rate_limiter.on_success()
                    self.rate_limiter.batch_pause()

                # Progress report every 10 batches.
                if (i // batch_size) % 10 == 0 and i > 0:
                    elapsed = time.monotonic() - t0
                    rate = processed_count / elapsed if elapsed > 0 else 0
                    logger.info(
                        "Progress: %d/%d symbols (%.0f/s), %d ok, %d failed, %.0fs elapsed",
                        processed_count, len(symbols), rate, ok_count, fail_count, elapsed,
                    )

        # ── 5. Finish ───────────────────────────────────────────────
        _finish_result(
            result,
            t0=t0,
            symbols_ok=ok_count,
            symbols_failed=fail_count,
            rows_inserted=total_inserted,
            failed_message=f"No data returned for all {fail_count} symbols",
        )

        self.storage.log_finish(
            result.log_id,
            status=result.status,
            symbols_ok=ok_count,
            symbols_failed=fail_count,
            rows_inserted=total_inserted,
            error_msg=result.error_msg,
        )

        logger.info(
            "%s/%s: %s. %d/%d symbols ok, %d rows inserted in %.1fs",
            market, self.source.name, result.status,
            ok_count, result.symbols_total, total_inserted,
            result.elapsed_seconds,
        )
        return result

    # ── intraday ────────────────────────────────────────────────────

    def run_intraday(
        self,
        market: str,
        *,
        interval: str = "15m",
        start_date: str = "",
        end_date: str = "",
        symbols: list[str] | None = None,
        dry_run: bool = False,
    ) -> DownloadResult:
        """Download intraday OHLCV for *market* and upsert into storage."""
        t0 = time.monotonic()

        if not end_date:
            end_date = latest_trade_date()
        if not start_date:
            start_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

        if symbols is None:
            symbols = resolve_symbols(market, self.source)

        if not symbols:
            return DownloadResult(
                market=market, source=self.source.name,
                start_date=start_date, end_date=end_date,
                status="failed", error_msg="No symbols resolved",
            )

        result = DownloadResult(
            market=market, source=self.source.name,
            start_date=start_date, end_date=end_date,
            symbols_total=len(symbols),
        )

        if dry_run:
            result.status = "ok"
            result.elapsed_seconds = time.monotonic() - t0
            logger.info(
                "[dry-run] intraday %s/%s: %d symbols, %s → %s",
                market, self.source.name, len(symbols), start_date, end_date,
            )
            return result

        result.log_id = self.storage.log_start(
            market=market, source=self.source.name,
            start_date=start_date, end_date=end_date,
            symbols_total=len(symbols),
        )

        total_inserted, ok_count, fail_count = 0, 0, 0
        batch_size = config.rate_limit.batch_size if self.rate_limiter else 50

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i: i + batch_size]
            try:
                batch_data = self.source.fetch_intraday_range(
                    batch, start_date, end_date, interval=interval,
                )
            except Exception as exc:
                logger.error("intraday batch %d failed: %s", i, exc)
                fail_count += len(batch)
                if self.rate_limiter:
                    self.rate_limiter.on_error(exc)
                continue
            batch_data = batch_data or {}

            batch_ok, batch_failed, batch_rows = _write_symbol_frames(
                batch,
                batch_data,
                lambda frame: self.storage.upsert_intraday(
                    frame, source=self.source.name, interval=interval,
                ),
                label="intraday",
            )
            ok_count += batch_ok
            fail_count += batch_failed
            total_inserted += batch_rows

            if self.rate_limiter:
                self.rate_limiter.on_success()
                self.rate_limiter.batch_pause()

        _finish_result(
            result,
            t0=t0,
            symbols_ok=ok_count,
            symbols_failed=fail_count,
            rows_inserted=total_inserted,
            failed_message=f"No data returned for all {fail_count} symbols",
        )

        self.storage.log_finish(
            result.log_id, status=result.status,
            symbols_ok=ok_count, symbols_failed=fail_count,
            rows_inserted=total_inserted, error_msg=result.error_msg,
        )
        return result

    # ── capital flow ───────────────────────────────────────────────

    def run_capital_flow(
        self,
        market: str,
        *,
        trade_date: str = "",
        symbols: list[str] | None = None,
        dry_run: bool = False,
    ) -> DownloadResult:
        """Download capital flow for *market* and upsert into storage."""
        t0 = time.monotonic()

        if not trade_date:
            trade_date = latest_trade_date()

        if symbols is None:
            symbols = resolve_symbols(market, self.source)

        if not symbols:
            return DownloadResult(
                market=market, source=self.source.name,
                start_date=trade_date, end_date=trade_date,
                status="failed", error_msg="No symbols resolved",
            )

        result = DownloadResult(
            market=market, source=self.source.name,
            start_date=trade_date, end_date=trade_date,
            symbols_total=len(symbols),
        )

        if dry_run:
            result.status = "ok"
            result.elapsed_seconds = time.monotonic() - t0
            logger.info(
                "[dry-run] capital-flow %s/%s: %d symbols, %s",
                market, self.source.name, len(symbols), trade_date,
            )
            return result

        result.log_id = self.storage.log_start(
            market=market, source=self.source.name,
            start_date=trade_date, end_date=trade_date,
            symbols_total=len(symbols),
        )

        total_inserted, ok_count, fail_count = 0, 0, 0
        batch_size = config.rate_limit.batch_size if self.rate_limiter else 25

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i: i + batch_size]
            try:
                batch_data = self.source.fetch_capital_flow(batch, trade_date)
            except Exception as exc:
                logger.error("capital-flow batch %d failed: %s", i, exc)
                fail_count += len(batch)
                if self.rate_limiter:
                    self.rate_limiter.on_error(exc)
                continue
            batch_data = batch_data or {}

            batch_ok, batch_failed, batch_rows = _write_symbol_frames(
                batch,
                batch_data,
                lambda frame: self.storage.upsert_capital_flow(frame, source=self.source.name),
                label="capital-flow",
            )
            ok_count += batch_ok
            fail_count += batch_failed
            total_inserted += batch_rows

            if self.rate_limiter:
                self.rate_limiter.on_success()
                self.rate_limiter.batch_pause()

        _finish_result(
            result,
            t0=t0,
            symbols_ok=ok_count,
            symbols_failed=fail_count,
            rows_inserted=total_inserted,
            failed_message=f"No data returned for all {fail_count} symbols",
        )

        self.storage.log_finish(
            result.log_id, status=result.status,
            symbols_ok=ok_count, symbols_failed=fail_count,
            rows_inserted=total_inserted, error_msg=result.error_msg,
        )
        return result


    # ── full mode ──────────────────────────────────────────────────

    def run_full(
        self,
        market: str = "a_share",
        *,
        intraday: bool = True,
        capital_flow: bool = False,
        stock_info: bool = True,
        days_back: int = 30,
        dry_run: bool = False,
    ) -> list[DownloadResult]:
        """Chain all data types sequentially with auto-adjusted delays.

        Order: stock info → daily → intraday → capital flow.
        Each HTTP-sensitive step respects the global rate-limit config.

        Returns:
            List of :class:`DownloadResult`, one per step.
        """
        results: list[DownloadResult] = []

        # ── 0. Stock info (one bulk request, no rate concern) ─────
        if stock_info:
            n = self.sync_stock_info(dry_run=dry_run)
            results.append(DownloadResult(
                market=market, source=self.source.name,
                start_date="", end_date="",
                status="ok" if n > 0 else "ok (no new)",
                symbols_total=n, symbols_ok=n,
            ))

        end = latest_trade_date()
        end_dt = pd.Timestamp(end)

        # ── 1. Daily OHLCV via TDX offline ZIP (complete, fast) ──
        all_symbols = resolve_symbols(market, self.source)

        latest_map = self.storage.get_latest_date_per_code(all_symbols) if all_symbols else {}
        missing = [s for s in all_symbols if s not in latest_map or pd.Timestamp(latest_map[s]) < end_dt]

        if not missing:
            logger.info("Daily: all %d symbols up to date, skipping", len(all_symbols))
            r = DownloadResult(market=market, source="(cached)", status="ok (cached)",
                               start_date=str(end), end_date=str(end),
                               symbols_total=len(all_symbols), symbols_ok=len(all_symbols))
            results.append(r)
        else:
            logger.info("Daily: %d/%d symbols need data, using tdx_offline ZIP", len(missing), len(all_symbols))
            start = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            r = _download_with_fallback(
                "tdx_offline", market, start, end, missing, dry_run, data_type="daily",
            )
            results.append(r)

        # ── 2. Intraday via Tencent (60m, 30m, 15m) ────────────────
        if intraday and r.status != "failed":
            intra_start = (date.today() - timedelta(days=min(days_back, 5))).strftime("%Y-%m-%d")
            for iv in ("60m", "30m", "15m"):
                ri = _download_with_fallback(
                    "tencent", market, intra_start, end, None, dry_run,
                    data_type="intraday", interval=iv,
                )
                results.append(ri)

        # ── 3. Capital flow (THS only) ─────────────────────────────
        if capital_flow:
            cf_latest = self.storage.conn.execute(
                "SELECT MAX(trade_date) FROM capital_flow WHERE code LIKE '%.SH' OR code LIKE '%.SZ'"
            ).fetchone()
            if cf_latest and cf_latest[0] and str(cf_latest[0]) >= end:
                logger.info("Capital flow already up to date (%s), skipping", cf_latest[0])
                results.append(DownloadResult(market=market, source="(cached)", status="ok (cached)",
                                              start_date=str(cf_latest[0]), end_date=str(cf_latest[0])))
            else:
                rc = _download_with_fallback(
                    "ths", market, end, end, None, dry_run,
                    data_type="capital_flow",
                )
                results.append(rc)

        return results

    # ── stock info sync ──────────────────────────────────────────────

    def sync_stock_info(self, market: str = "a_share", *, dry_run: bool = False) -> int:
        """Pull stock basic info + market cap.

        Tries Tencent Finance first (never IP-banned).  Falls back to
        AKShare if Tencent is unreachable.
        """
        records: list[dict[str, str]] = []

        # ── Try Tencent first ─────────────────────────────────────
        try:
            from src.data.sources.tencent_source import TencentSource

            ts = TencentSource()
        except ImportError:
            ts = None

        if ts is not None:
            logger.info("Fetching stock info from Tencent Finance...")
            try:
                import akshare as ak
                df = ak.stock_info_a_code_name()
                codes = []
                for _, row in df.iterrows():
                    c = str(row.get("code", ""))
                    if c and len(c) == 6:
                        codes.append(f"{c}.{'SH' if c.startswith('6') else ('BJ' if c.startswith(('4','8')) else 'SZ')}")
            except Exception:
                codes = []

            if codes:
                records = ts.fetch_stock_info(codes)  # Fetch ALL, no cap
                if records:
                    logger.info("Tencent: got %d stock info records", len(records))
                    if not dry_run:
                        n = self.storage.upsert_stock_info(records)
                        return n
                    return len(records)

        # ── Fallback: AKShare ─────────────────────────────────────
        logger.info("Tencent unavailable, falling back to AKShare...")
        try:
            import akshare as ak
        except ImportError:
            logger.error("AKShare not installed — cannot sync stock info")
            return 0

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return 0

        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            if not code:
                continue
            market = "SH" if code.startswith("6") else ("BJ" if code.startswith(("4", "8")) else "SZ")
            records.append({
                "code": f"{code}.{market}",
                "name": str(row.get("名称", "")),
                "market": market,
                "exchange": {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(market, ""),
                "float_market_cap": float(row.get("流通市值", 0) or 0),
                "total_market_cap": float(row.get("总市值", 0) or 0),
                "float_shares": float(row.get("流通股", 0) or 0),
                "source": "akshare",
            })

        if dry_run:
            return len(records)
        return self.storage.upsert_stock_info(records)


# ── fallback chains ───────────────────────────────────────────────────


def _try_download(
    source_name: str,
    market: str,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    dry_run: bool,
    data_type: str,  # "daily" | "intraday" | "capital_flow"
    interval: str = "15m",
) -> DownloadResult | None:
    """Try one source. Returns None if the source is unavailable."""
    try:
        dl = get_downloader(source=source_name)
    except ValueError:
        return None

    if data_type == "daily":
        return dl.run(market=market, start_date=start_date, end_date=end_date,
                      symbols=symbols, dry_run=dry_run)
    elif data_type == "intraday":
        return dl.run_intraday(market=market, interval=interval,
                               start_date=start_date, end_date=end_date,
                               symbols=symbols, dry_run=dry_run)
    else:
        return dl.run_capital_flow(market=market, trade_date=end_date,
                                   symbols=symbols, dry_run=dry_run)


def _download_with_fallback(
    source: str,
    market: str,
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    dry_run: bool,
    data_type: str = "daily",
    interval: str = "15m",
) -> DownloadResult:
    """Try *source*, then each fallback, until one succeeds."""
    results: list[DownloadResult] = []

    for name in fallback_chain(source, data_type=data_type):
        r = _try_download(name, market, start_date, end_date, symbols, dry_run, data_type, interval)
        if r is None:
            logger.info("Source %r unavailable, trying next...", name)
            continue
        results.append(r)
        if r.status != "failed":
            if name != source:
                logger.info("Fell back from %r to %r (status=%s)", source, name, r.status)
            return r
        logger.warning("Source %r returned failed, trying next...", name)

    # All sources failed — return the last (or empty) result.
    if results:
        return results[-1]
    return DownloadResult(market=market, source=source, start_date=start_date, end_date=end_date,
                          status="failed", error_msg="All sources unavailable")


# ── factory ─────────────────────────────────────────────────────────────


def get_downloader(
    source: str = "tdx",
    *,
    storage: Storage | None = None,
    rate_limiter: RateLimiter | None = None,
    **source_kwargs,
) -> Downloader:
    """Create a :class:`Downloader` for the named source.

    Args:
        source: Data source name.
        storage: Optional storage instance for dependency injection.
        rate_limiter: Optional rate limiter for HTTP-sensitive sources.
        **source_kwargs: Passed to the source constructor.

    Returns:
        Configured :class:`Downloader`.

    Raises:
        ValueError: If the source name is unknown or the required
            dependencies are not installed.
    """
    src = create_source(source, **source_kwargs)

    if not src.is_available():
        raise ValueError(
            f"Source {source!r} is not available. "
            f"Install required dependencies and retry."
        )

    return Downloader(src, storage=storage, rate_limiter=rate_limiter)


# ── helpers ─────────────────────────────────────────────────────────────


def _latest_trade_date() -> str:
    """Backward-compatible wrapper for older internal imports."""
    return latest_trade_date()
