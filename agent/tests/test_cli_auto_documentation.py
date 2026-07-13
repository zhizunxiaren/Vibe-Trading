"""Regression tests for automatic CLI turn documentation."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from typing import Any


class _FakeDashboard:
    def __init__(self, prompt: str, max_iter: int) -> None:
        self.prompt = prompt
        self.max_iter = max_iter
        self.live = None

    def render(self) -> str:
        return ""

    def finish(self, result: dict[str, Any], elapsed: float) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeLive:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __enter__(self) -> "_FakeLive":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def _patch_turn_runner(
    monkeypatch,
    work_dir: Path,
    result: dict[str, Any],
    *,
    session_id: str = "sess_docs",
) -> Any:
    cli_main = importlib.import_module("cli.main")
    legacy = importlib.import_module("cli._legacy")

    from src.session.store import SessionStore

    monkeypatch.setattr(cli_main, "_SESSION_STORE_CACHE", SessionStore(work_dir / "sessions"))
    monkeypatch.setattr(cli_main, "_new_session", lambda prompt_preview: session_id)
    monkeypatch.setattr(legacy, "_RunDashboard", _FakeDashboard)
    monkeypatch.setattr(legacy, "_run_agent", lambda *args, **kwargs: result)
    monkeypatch.setattr("rich.live.Live", _FakeLive)
    return cli_main


def test_cli_turn_appends_visible_analysis_document(
    monkeypatch,
) -> None:
    work_dir = Path("agent/.pytest_tmp") / f"auto_doc_{uuid.uuid4().hex}"
    result = {
        "status": "success",
        "content": "AAPL moved lower after weak guidance.",
        "run_id": "run_123",
        "react_trace": [
            {"type": "tool_result", "tool": "get_market_data"},
            {"type": "tool_result", "tool": "stock_news"},
            {"type": "assistant_delta", "content": "hidden stream"},
        ],
    }
    cli_main = _patch_turn_runner(monkeypatch, work_dir, result)
    ctx = cli_main.InteractiveContext(max_iter=3)

    cli_main._run_one_turn("Analyze AAPL today", ctx)

    doc = work_dir / "sessions" / "sess_docs" / "analysis.md"
    text = doc.read_text(encoding="utf-8")
    assert "# CLI Session Analysis" in text
    assert "Analyze AAPL today" in text
    assert "AAPL moved lower after weak guidance." in text
    assert "run_123" in text
    assert "Tools: 2" in text
    assert "assistant_delta" not in text


def test_cli_turn_documents_metadata_without_assistant_content(
    monkeypatch,
) -> None:
    work_dir = Path("agent/.pytest_tmp") / f"auto_doc_{uuid.uuid4().hex}"
    result = {
        "status": "failed",
        "content": "",
        "reason": "provider unavailable",
        "run_id": "run_empty",
        "react_trace": [],
    }
    cli_main = _patch_turn_runner(monkeypatch, work_dir, result, session_id="sess_empty")
    ctx = cli_main.InteractiveContext(max_iter=3)

    cli_main._run_one_turn("Run a quick market scan", ctx)

    doc = work_dir / "sessions" / "sess_empty" / "analysis.md"
    text = doc.read_text(encoding="utf-8")
    assert "Run a quick market scan" in text
    assert "Status: failed" in text
    assert "Run ID: `run_empty`" in text
    assert "_No assistant content recorded._" in text
