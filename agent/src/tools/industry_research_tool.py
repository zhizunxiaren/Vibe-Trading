"""Industry research tool: search financial and technical media sites for industry chain analysis."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from src.agent.progress import emit_progress
from src.agent.tools import BaseTool
from src.security.scanner import with_security_warnings

logger = logging.getLogger(__name__)

# Default Chinese financial news sites for policy/industry-level research.
_FINANCIAL_SITES = [
    "cls.cn",
    "eastmoney.com",
    "10jqka.com",
    "finance.sina.com.cn",
    "xueqiu.com",
]

# Default English technical media sites for deep technical research
# (chip specs, process details, material parameters, teardowns, benchmarks).
_TECHNICAL_SITES = [
    "anandtech.com",
    "semianalysis.com",
    "tomshardware.com",
    "ieee.org",
    "semiengineering.com",
    "chipsandcheese.com",
    "servethehome.com",
    "nextplatform.com",
    "arstechnica.com",
    "hpcwire.com",
]

_MAX_ARTICLES_PER_SITE = 5
_DEFAULT_ARTICLES_PER_SITE = 3
_SEARCH_DELAY_SECONDS = 1.0


def _resolve_ddgs() -> type:
    """Return the DDGS class from whichever package is installed."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore[no-redef]
    return DDGS


def _days_to_timelimit(days: int) -> str | None:
    """Convert a day count to a DDGS ``timelimit`` value.

    Args:
        days: Number of days to look back.

    Returns:
        ``"d"`` for ≤1 day, ``"w"`` for ≤7 days, ``"m"`` for ≤90 days,
        ``"y"`` for ≤365 days, ``None`` for anything larger.
    """
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 90:
        return "m"
    if days <= 365:
        return "y"
    return None


def _search_site(
    ddgs_cls: type,
    query: str,
    site_domain: str,
    max_results: int,
    timelimit: str | None = None,
) -> list[dict[str, str]]:
    """Search DuckDuckGo for articles about a topic on a specific site.

    Uses DDGS ``site:`` operator for targeted results, with hostname
    post-filter as a safety net for any results that slip through.

    Args:
        ddgs_cls: The DDGS class to instantiate.
        query: Search query string (should NOT include ``site:`` — this
            function prepends it automatically).
        site_domain: Domain to filter results for (e.g. "cls.cn").
        max_results: Maximum raw results to request from DDGS.
        timelimit: Optional DDGS time filter (``"d"``, ``"w"``, ``"m"``, ``"y"``).

    Returns:
        List of dicts with keys: title, url, snippet.
    """
    # Prepend site: operator for targeted search.
    site_query = f"site:{site_domain} {query}"

    try:
        with ddgs_cls() as ddgs:
            kwargs: dict[str, object] = {"max_results": max_results}
            if timelimit:
                kwargs["timelimit"] = timelimit
            raw = list(ddgs.text(site_query, **kwargs))
    except Exception as exc:
        logger.warning("DDGS search failed for site=%s query=%s: %s", site_domain, query, exc)
        return []

    results: list[dict[str, str]] = []
    for r in raw:
        url = r.get("href", "")
        if not url:
            continue
        try:
            host = urlsplit(url).hostname or ""
        except Exception:
            continue
        # Post-filter: only keep results whose hostname contains the target domain.
        # Using `site:` in the query gets most results, this catches edge cases.
        if site_domain not in host:
            continue
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "snippet": r.get("body", ""),
        })
    return results


class IndustryResearchTool(BaseTool):
    """Search financial and technical media sites for industry articles.

    Returns article metadata (title, url, snippet) grouped by source.
    For full article text, use ``read_url`` on the returned URLs — this
    keeps the search fast and lets you selectively fetch only the most
    relevant articles.
    """

    name = "industry_research"
    description = (
        "Search industry articles from financial or technical media sites. "
        "Returns metadata (title, url, snippet) grouped by source. "
        "Use read_url on specific URLs for full article text. "
        "Modes: 'financial_cn' (Chinese financial/policy news, default), "
        "'technical_en' (English technical deep-dives on chip specs, process "
        "details, benchmarks, teardowns, etc.), or 'both'. "
        "Use as supplementary data during product decomposition — search for "
        "latest specs, process parameters, and technology breakthroughs for "
        "specific components identified in the decomposition."
    )
    parameters = {
        "type": "object",
        "properties": {
            "industry": {
                "type": "string",
                "description": (
                    "Industry name or keyword. Use Chinese for financial_cn mode "
                    "(e.g. 'AI产业', '半导体'), English for technical_en mode "
                    "(e.g. 'H100 chip', 'EUV lithography', 'HBM3 memory')"
                ),
            },
            "search_mode": {
                "type": "string",
                "enum": ["financial_cn", "technical_en", "both"],
                "description": (
                    "Search mode: 'financial_cn' (default) searches Chinese financial "
                    "sites for policy/industry news. 'technical_en' searches English "
                    "technical media for chip specs, process details, benchmarks, "
                    "teardowns. 'both' does both sequentially — when used with a "
                    "custom 'query' parameter, the same query text is applied across "
                    "all sites regardless of type."
                ),
                "default": "financial_cn",
            },
            "sites": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Custom list of site domain names. Overrides the default site "
                    "list for the selected search_mode. "
                    "Financial mode defaults: cls.cn, eastmoney.com, 10jqka.com, "
                    "finance.sina.com.cn, xueqiu.com. "
                    "Technical mode defaults: anandtech.com, semianalysis.com, "
                    "tomshardware.com, ieee.org, semiengineering.com, etc."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional custom search query. If not provided, a query is "
                    "auto-constructed from the industry parameter. "
                    "Use this for highly specific technical queries like "
                    "'NVIDIA B200 transistor count die size' or "
                    "'TSMC N3P process specs SRAM density'."
                ),
            },
            "days": {
                "type": "integer",
                "description": "How many days back to consider (default 30, max 90)",
                "default": 30,
            },
            "max_articles_per_site": {
                "type": "integer",
                "description": "Max article metadata entries per site (default 3, max 5)",
                "default": 3,
            },
        },
        "required": ["industry"],
    }
    repeatable = True
    is_readonly = True

    @classmethod
    def check_available(cls) -> bool:
        """Available if DuckDuckGo search package is installed."""
        try:
            _resolve_ddgs()
            return True
        except ImportError:
            return False

    def execute(self, **kwargs: Any) -> str:
        """Run industry research across configured news sites.

        Args:
            **kwargs: Must include ``industry``. Optionally ``search_mode``,
                ``sites``, ``query``, ``days``, ``max_articles_per_site``.

        Returns:
            JSON with per-site article metadata (title, url, snippet).
        """
        try:
            return self._execute_impl(**kwargs)
        except Exception as exc:
            logger.exception("industry_research failed")
            return json.dumps(
                {"status": "error", "error": f"industry_research failed: {exc}"},
                ensure_ascii=False,
            )

    def _execute_impl(self, **kwargs: Any) -> str:
        industry = str(kwargs["industry"]).strip()
        search_mode = str(kwargs.get("search_mode", "financial_cn")).strip()
        custom_query = kwargs.get("query", "").strip() if kwargs.get("query") else ""

        # Resolve site list.
        custom_sites = kwargs.get("sites")
        if custom_sites is not None:
            if isinstance(custom_sites, str):
                custom_sites = [s.strip() for s in custom_sites.split(",") if s.strip()]
            sites = [str(s).strip() for s in custom_sites if str(s).strip()]
        elif search_mode == "technical_en":
            sites = list(_TECHNICAL_SITES)
        elif search_mode == "both":
            sites = list(_FINANCIAL_SITES) + list(_TECHNICAL_SITES)
        else:
            sites = list(_FINANCIAL_SITES)

        days = min(int(kwargs.get("days", 30)), 90)
        max_articles = min(int(kwargs.get("max_articles_per_site", _DEFAULT_ARTICLES_PER_SITE)), _MAX_ARTICLES_PER_SITE)

        DDGS = _resolve_ddgs()
        timelimit = _days_to_timelimit(days)

        query_time = datetime.now(timezone.utc).isoformat()
        total_articles = 0
        results: list[dict[str, Any]] = []

        for site in sites:
            # Build search query.
            if custom_query:
                search_query = custom_query
            elif search_mode == "technical_en" or (search_mode == "both" and site in _TECHNICAL_SITES):
                search_query = f"{industry} specs technology details"
            else:
                # Financial/policy sites: use industry keyword directly.
                # ``_search_site`` prepends ``site:`` for targeted search.
                search_query = industry

            emit_progress("searching", message=f"搜索 {site}: {search_query[:60]}")

            articles = _search_site(DDGS, search_query, site, max_results=max_articles * 2, timelimit=timelimit)
            articles = articles[:max_articles]
            total_articles += len(articles)

            results.append({
                "site": site,
                "articles_count": len(articles),
                "articles": articles,
            })

            if site != sites[-1]:
                time.sleep(_SEARCH_DELAY_SECONDS)

        payload: dict[str, Any] = {
            "status": "ok",
            "industry": industry,
            "search_mode": search_mode,
            "query_time": query_time,
            "days_searched": days,
            "sites_searched": sites,
            "total_articles": total_articles,
            "results": results,
        }

        # Apply security scanning to article metadata fields.
        payload = with_security_warnings(
            payload,
            fields=(
                "results.*.articles.*.snippet",
                "results.*.articles.*.title",
            ),
        )
        return json.dumps(payload, ensure_ascii=False)
