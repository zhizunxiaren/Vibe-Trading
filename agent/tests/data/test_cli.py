"""Regression tests for the standalone data downloader CLI."""

from __future__ import annotations

from types import SimpleNamespace

from src.data import __main__ as data_cli
from src.data.downloader import DownloadResult


def test_status_prints_status_counts_rows_and_date_range(monkeypatch, capsys) -> None:
    class FakeQuery:
        def fetchall(self):
            return [
                (
                    1,
                    "a_share",
                    "tdx",
                    "2026-06-01",
                    "2026-06-02",
                    "ok",
                    10,
                    9,
                    1,
                    123,
                    "started",
                    "finished",
                )
            ]

    class FakeConn:
        def execute(self, _sql: str):
            return FakeQuery()

    class FakeStorage:
        conn = FakeConn()

    monkeypatch.setattr("src.data.storage.Storage", FakeStorage)

    assert data_cli.cmd_status(SimpleNamespace()) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[2].split()[:9] == [
        "1",
        "a_share",
        "tdx",
        "ok",
        "9/10",
        "123",
        "2026-06-01",
        "->",
        "2026-06-02",
    ]


def test_full_download_prints_labels_for_all_default_steps(monkeypatch, capsys) -> None:
    class FakeDownloader:
        def run_full(self, **_kwargs):
            return [
                DownloadResult("a_share", "tencent", "", "", status="ok", symbols_ok=1),
                DownloadResult("a_share", "tdx_offline", "2026-06-01", "2026-06-02", status="ok", symbols_ok=2),
                DownloadResult("a_share", "tencent", "2026-06-01", "2026-06-02", status="ok", symbols_ok=3),
                DownloadResult("a_share", "tencent", "2026-06-01", "2026-06-02", status="ok", symbols_ok=4),
                DownloadResult("a_share", "tencent", "2026-06-01", "2026-06-02", status="ok", symbols_ok=5),
            ]

    monkeypatch.setattr("src.data.get_downloader", lambda source: FakeDownloader())
    args = SimpleNamespace(source="auto", mode="full", market="a_share", dry_run=False)

    assert data_cli.cmd_download(args) == 0

    output = capsys.readouterr().out
    assert "stock_info:" in output
    assert "daily:" in output
    assert "intraday_60m:" in output
    assert "intraday_30m:" in output
    assert "intraday_15m:" in output
    assert "intraday_5m:" not in output


def test_download_interval_all_runs_60_30_15(monkeypatch, capsys) -> None:
    calls: list[str] = []

    class FakeDownloader:
        def run_intraday(self, **kwargs):
            interval = kwargs["interval"]
            calls.append(interval)
            return DownloadResult(
                "a_share",
                "tencent",
                "2026-06-24",
                "2026-06-24",
                status="ok",
                symbols_total=2,
                symbols_ok=2,
                rows_inserted=8,
            )

    monkeypatch.setattr("src.data.get_downloader", lambda source: FakeDownloader())
    args = SimpleNamespace(
        source="tencent",
        mode="single",
        market="a_share",
        interval="all",
        from_date="2026-06-24",
        to_date="2026-06-24",
        dry_run=False,
    )

    assert data_cli.cmd_download(args) == 0

    assert calls == ["60m", "30m", "15m"]
    output = capsys.readouterr().out
    assert "Downloading a_share (60m) via tencent..." in output
    assert "Downloading a_share (30m) via tencent..." in output
    assert "Downloading a_share (15m) via tencent..." in output
