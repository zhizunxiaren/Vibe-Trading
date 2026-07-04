"""Tests for exposing analytics tools through the MCP server."""

from __future__ import annotations

import asyncio

import mcp_server


def test_mcp_server_exposes_analytics_tools() -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}

    assert "list_analytics_recipes" in names
    assert "run_analysis" in names
