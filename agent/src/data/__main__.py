"""Standalone CLI for the daily data downloader.

Paths are resolved from ``<project_root>/data-config.json``:

.. code-block:: json

    { "data_dir": "I:\\\\Alpha\\\\trading-data" }

Usage::

    python -m src.data download --market a_share --source tdx
    python -m src.data download --market all --source auto
    python -m src.data status
"""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_download(args: argparse.Namespace) -> int:
    """Run a download (single type or full chained mode)."""
    from src.data import get_downloader

    if args.source == "auto":
        source = "tencent"
    else:
        source = args.source

    # ── Full mode: chain all data types ───────────────────────────
    if getattr(args, "mode", "single") == "full":
        try:
            dl = get_downloader(source=source)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return 1

        print(f"Full download via {source}...")
        results = dl.run_full(
            market=args.market if args.market != "all" else "a_share",
            dry_run=args.dry_run,
        )
        steps = ["stock_info", "daily", "intraday_60m", "intraday_30m", "intraday_15m", "capital_flow"]
        exit_code = 0
        for idx, r in enumerate(results):
            label = steps[idx] if idx < len(steps) else f"step_{idx + 1}"
            tag = "[dry-run] " if args.dry_run else ""
            print(f"  {tag}{label}: {r.status} | {r.symbols_ok} symbols | {r.rows_inserted} rows | {r.elapsed_seconds:.1f}s")
            if r.status == "failed" and label == "daily":
                exit_code = 1
        return exit_code

    # ── Single mode (original behaviour) ──────────────────────────
    markets = ["a_share"] if args.market != "all" else ["a_share", "hk_equity"]
    source_map = {m: source for m in markets}

    interval = getattr(args, "interval", "1D") or "1D"
    intraday_intervals = ("60m", "30m", "15m") if interval == "all" else (interval,)
    is_intraday = interval in ("15m", "30m", "60m", "all")

    exit_code = 0
    for market in markets:
        src_name = source_map.get(market, source)
        try:
            dl = get_downloader(source=src_name)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return 1

        if args.dry_run:
            print(f"  [dry-run] no data will be written")

        if is_intraday:
            for intraday_interval in intraday_intervals:
                print(f"Downloading {market} ({intraday_interval}) via {src_name}...")
                result = dl.run_intraday(
                    market=market, interval=intraday_interval,
                    start_date=args.from_date or "",
                    end_date=args.to_date or "",
                    dry_run=args.dry_run,
                )
                print(
                    f"  {result.status}: {result.symbols_ok}/{result.symbols_total} symbols, "
                    f"{result.rows_inserted} rows in {result.elapsed_seconds:.1f}s"
                )
                if result.error_msg:
                    print(f"  error: {result.error_msg}")
                    exit_code = 1
        else:
            print(f"Downloading {market} (daily) via {src_name}...")
            result = dl.run(
                market=market,
                start_date=args.from_date or "",
                end_date=args.to_date or "",
                dry_run=args.dry_run,
            )

            print(
                f"  {result.status}: {result.symbols_ok}/{result.symbols_total} symbols, "
                f"{result.rows_inserted} rows in {result.elapsed_seconds:.1f}s"
            )
            if result.error_msg:
                print(f"  error: {result.error_msg}")
                exit_code = 1

    return exit_code


def cmd_capital_flow(args: argparse.Namespace) -> int:
    """Download capital flow data."""
    from src.data import get_downloader

    markets: list[str] = []
    if args.market == "all":
        markets = ["a_share"]
    else:
        markets = [args.market]

    src_name = args.source if args.source != "auto" else "ths"

    exit_code = 0
    for market in markets:
        try:
            dl = get_downloader(source=src_name)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return 1

        trade_date = getattr(args, "date", "") or ""
        print(f"Downloading capital flow for {market} via {src_name}...")
        if args.dry_run:
            print(f"  [dry-run] no data will be written")

        result = dl.run_capital_flow(
            market=market,
            trade_date=trade_date,
            dry_run=args.dry_run,
        )

        print(
            f"  {result.status}: {result.symbols_ok}/{result.symbols_total} symbols, "
            f"{result.rows_inserted} rows in {result.elapsed_seconds:.1f}s"
        )
        if result.error_msg:
            print(f"  error: {result.error_msg}")
            exit_code = 1

    return exit_code


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Show download status from the log table."""
    from src.data.storage import Storage

    storage = Storage()
    rows = storage.conn.execute(
        "SELECT id, market, source, start_date, end_date, status, "
        "symbols_total, symbols_ok, symbols_failed, rows_inserted, "
        "started_at, finished_at "
        "FROM download_log ORDER BY id DESC LIMIT 10"
    ).fetchall()

    if not rows:
        print("No download history.")
        return 0

    print(f"{'ID':<5} {'Market':<12} {'Source':<6} {'Status':<8} {'OK/Total':<12} {'Rows':<8} {'Date Range'}")
    print("-" * 80)
    for row in rows:
        print(
            f"{row[0]:<5} {row[1]:<12} {row[2]:<6} {row[5]:<8} "
            f"{row[7]}/{row[6]:<10} {row[9]:<8} {row[3]} -> {row[4]}"
        )
    return 0


def cmd_sync_info(args: argparse.Namespace) -> int:
    """Sync stock basic info from AKShare (one bulk request, no IP ban risk)."""
    from src.data import get_downloader

    try:
        dl = get_downloader(source="ths")
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print("Syncing stock info + market cap (single AKShare request)...")
    n = dl.sync_stock_info(dry_run=args.dry_run)
    tag = "[dry-run] would upsert" if args.dry_run else "Upserted"
    print(f"  {tag} {n} records")
    return 0


def cmd_latest(args: argparse.Namespace) -> int:  # noqa: ARG001
    """Show the latest stored trade date per market."""
    from src.data.storage import Storage

    storage = Storage()
    for market in ("a_share", "hk_equity"):
        latest = storage.get_latest_date(market)
        label = {"a_share": "A-Share", "hk_equity": "HK Equity"}.get(market, market)
        print(f"  {label}: {latest or '(no data)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m src.data``."""
    parser = argparse.ArgumentParser(
        prog="python -m src.data",
        description="Daily market data downloader for A-share and HK equity.",
    )
    sub = parser.add_subparsers(dest="command", help="Commands")

    dl = sub.add_parser("download", help="Download daily OHLCV data")
    dl.add_argument("--market", choices=["a_share", "hk_equity", "all"],
                    default="a_share", help="Market to download (default: a_share)")
    dl.add_argument("--source", choices=["tencent", "tdx_offline", "tdx", "ths", "auto"],
                    default="auto", help="Data source (default: auto)")
    dl.add_argument("--mode", choices=["single", "full"],
                    default="single", help="single=one data type, full=all types chained")
    dl.add_argument("--interval", choices=["1D", "15m", "30m", "60m", "all"],
                    default="1D", help="Bar interval (default: 1D daily)")
    dl.add_argument("--from-date", help="Start date YYYY-MM-DD (default: incremental)")
    dl.add_argument("--to-date", help="End date YYYY-MM-DD (default: latest trade date)")
    dl.add_argument("--dry-run", action="store_true",
                    help="Resolve symbols and date window without fetching")
    dl.set_defaults(func=cmd_download)

    cf = sub.add_parser("capital-flow", help="Download daily capital flow (主力资金流向)")
    cf.add_argument("--market", choices=["a_share", "hk_equity", "all"],
                    default="a_share", help="Market (default: a_share)")
    cf.add_argument("--source", choices=["ths", "auto"],
                    default="auto", help="Data source (default: auto)")
    cf.add_argument("--date", help="Trade date YYYY-MM-DD (default: latest)")
    cf.add_argument("--dry-run", action="store_true",
                    help="Resolve without fetching")
    cf.set_defaults(func=cmd_capital_flow)

    st = sub.add_parser("status", help="Show recent download history")
    st.set_defaults(func=cmd_status)

    lt = sub.add_parser("latest", help="Show latest stored trade date per market")
    lt.set_defaults(func=cmd_latest)

    si = sub.add_parser("sync-info", help="Sync stock basic info + market cap (AKShare bulk)")
    si.add_argument("--dry-run", action="store_true", help="Show count without writing")
    si.set_defaults(func=cmd_sync_info)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    _setup_logging(verbose=getattr(args, "verbose", False))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
