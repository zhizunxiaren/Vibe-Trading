"""Tests for the industry_research tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from src.tools.industry_research_tool import (
    _FINANCIAL_SITES,
    _TECHNICAL_SITES,
    _days_to_timelimit,
    _search_site,
    IndustryResearchTool,
)


# ── Shared mock helpers ────────────────────────────────────────────────


def _mock_ddgs_cls() -> MagicMock:
    """Return a MagicMock DDGS class suitable for patching ``_resolve_ddgs``."""
    return MagicMock()


def _patch_execute_deps(mock_search_return=None):
    """Patch both ``_resolve_ddgs`` and ``_search_site`` for execute tests.

    Returns the mocked ``_search_site`` so callers can inspect calls.
    """
    if mock_search_return is None:
        mock_search_return = [{"title": "T", "url": "https://x.com/y", "snippet": "S"}]

    ddgs_patch = patch(
        "src.tools.industry_research_tool._resolve_ddgs",
        return_value=_mock_ddgs_cls(),
    )
    search_patch = patch(
        "src.tools.industry_research_tool._search_site",
        return_value=mock_search_return,
    )

    return ddgs_patch, search_patch


# ── Unit: _days_to_timelimit ──────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "days, expected",
    [
        (0, "d"),
        (1, "d"),
        (3, "w"),
        (7, "w"),
        (30, "m"),
        (90, "m"),
        (180, "y"),
        (365, "y"),
        (366, None),
        (999, None),
    ],
)
def test_days_to_timelimit(days: int, expected: str | None) -> None:
    assert _days_to_timelimit(days) == expected


# ── Unit: _search_site ────────────────────────────────────────────────


@pytest.mark.unit
def test_search_site_returns_filtered_results() -> None:
    """Results are filtered to the target domain and mapped to title/url/snippet."""
    mock_ddgs_cls = MagicMock()
    mock_ddgs = MagicMock()
    mock_ddgs_cls.return_value.__enter__.return_value = mock_ddgs

    mock_ddgs.text.return_value = [
        {"href": "https://www.cls.cn/article/123", "title": "T1", "body": "S1"},
        {"href": "https://other.com/post", "title": "T2", "body": "S2"},
        {"href": "https://www.cls.cn/article/456", "title": "T3", "body": "S3"},
        {"href": "", "title": "T4", "body": "S4"},  # no URL → skipped
    ]

    results = _search_site(
        mock_ddgs_cls, "光模块", "cls.cn", max_results=5, timelimit="m"
    )

    # Only cls.cn results, empty-href skipped
    assert len(results) == 2
    assert results[0] == {"title": "T1", "url": "https://www.cls.cn/article/123", "snippet": "S1"}
    assert results[1] == {"title": "T3", "url": "https://www.cls.cn/article/456", "snippet": "S3"}

    # Verify site: operator was prepended
    call_query = mock_ddgs.text.call_args[0][0]
    assert "site:cls.cn" in call_query
    assert "光模块" in call_query


@pytest.mark.unit
def test_search_site_graceful_on_ddgs_failure() -> None:
    """Returns empty list when DDGS raises, does not propagate exception."""
    mock_ddgs_cls = MagicMock()
    mock_ddgs_cls.return_value.__enter__.side_effect = RuntimeError("boom")

    results = _search_site(mock_ddgs_cls, "query", "site.com", max_results=3)
    assert results == []


# ── Tool: check_available ─────────────────────────────────────────────


@pytest.mark.unit
def test_check_available_returns_bool() -> None:
    """check_available returns True/False without raising."""
    result = IndustryResearchTool.check_available()
    assert isinstance(result, bool)


# ── Tool: execute ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_execute_financial_cn_mode() -> None:
    """Default mode searches Chinese financial sites."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps()

    with ddgs_patch, search_patch:
        result = json.loads(tool.execute(industry="光模块"))

    assert result["status"] == "ok"
    assert result["search_mode"] == "financial_cn"
    assert result["industry"] == "光模块"
    assert all(s in _FINANCIAL_SITES for s in result["sites_searched"])
    assert result["total_articles"] > 0


@pytest.mark.unit
def test_execute_technical_en_mode() -> None:
    """technical_en mode searches English technical sites."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps()

    with ddgs_patch, search_patch:
        result = json.loads(tool.execute(industry="H100 chip", search_mode="technical_en"))

    assert result["status"] == "ok"
    assert result["search_mode"] == "technical_en"
    assert all(s in _TECHNICAL_SITES for s in result["sites_searched"])


@pytest.mark.unit
def test_execute_both_mode() -> None:
    """both mode searches financial + technical sites."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps()

    with ddgs_patch, search_patch:
        result = json.loads(tool.execute(industry="光模块", search_mode="both"))

    assert result["status"] == "ok"
    assert result["search_mode"] == "both"
    # Sites should include both lists
    sites = result["sites_searched"]
    assert any(s in _FINANCIAL_SITES for s in sites)
    assert any(s in _TECHNICAL_SITES for s in sites)


@pytest.mark.unit
def test_execute_custom_sites_overrides_defaults() -> None:
    """Custom sites parameter replaces the default site list."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps()

    with ddgs_patch, search_patch:
        result = json.loads(tool.execute(industry="test", sites=["custom.io"]))

    assert result["status"] == "ok"
    assert result["sites_searched"] == ["custom.io"]


@pytest.mark.unit
def test_execute_custom_query() -> None:
    """Custom query is used directly instead of auto-constructed one."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps()

    with ddgs_patch, search_patch as mock_search:
        tool.execute(industry="光模块", query="800G DR8 LPO linear drive", search_mode="technical_en")

    # The custom query should be passed through to _search_site
    call_query = mock_search.call_args[0][1]
    assert call_query == "800G DR8 LPO linear drive"


@pytest.mark.unit
def test_execute_respects_days_and_max_articles() -> None:
    """days and max_articles_per_site parameters are respected."""
    tool = IndustryResearchTool()
    ddgs_patch, search_patch = _patch_execute_deps(
        mock_search_return=[
            {"title": "T1", "url": "https://cls.cn/1", "snippet": "S1"},
            {"title": "T2", "url": "https://cls.cn/2", "snippet": "S2"},
            {"title": "T3", "url": "https://cls.cn/3", "snippet": "S3"},
            {"title": "T4", "url": "https://cls.cn/4", "snippet": "S4"},
        ],
    )

    with ddgs_patch, search_patch:
        result = json.loads(tool.execute(
            industry="test",
            days=7,
            max_articles_per_site=2,
            sites=["cls.cn"],
        ))

    assert result["days_searched"] == 7
    # max_articles_per_site=2 should cap at 2 articles per site
    assert result["total_articles"] <= 2 * len(result["sites_searched"])


@pytest.mark.unit
def test_execute_error_returns_error_status() -> None:
    """Unhandled errors produce a structured error JSON response."""
    tool = IndustryResearchTool()

    with patch.object(tool, "_execute_impl", side_effect=RuntimeError("unexpected")):
        result = json.loads(tool.execute(industry="test"))

    assert result["status"] == "error"
    assert "unexpected" in result["error"]


# ── Tool: registration ────────────────────────────────────────────────


@pytest.mark.unit
def test_tool_is_discoverable_in_registry() -> None:
    """IndustryResearchTool is auto-discovered by the tool registry."""
    from src.tools import build_registry

    # Patch check_available so the tool is not skipped when ddgs is absent.
    with patch.object(IndustryResearchTool, "check_available", return_value=True):
        registry = build_registry()
        tool = registry.get("industry_research")

    assert tool is not None
    assert isinstance(tool, IndustryResearchTool)


@pytest.mark.unit
def test_tool_metadata() -> None:
    """Tool declares correct name, readonly, and repeatable flags."""
    tool = IndustryResearchTool()

    assert tool.name == "industry_research"
    assert tool.is_readonly is True
    assert tool.repeatable is True


@pytest.mark.unit
def test_tool_parameters_schema() -> None:
    """Parameter schema has the expected required and optional fields."""
    params = IndustryResearchTool.parameters

    assert "industry" in params["properties"]
    assert "industry" in params["required"]
    assert "search_mode" in params["properties"]
    assert "sites" in params["properties"]
    assert "query" in params["properties"]
    assert "days" in params["properties"]
    assert "max_articles_per_site" in params["properties"]
