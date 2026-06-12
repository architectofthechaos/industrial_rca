"""MCP host URL config (Sprint 5 WI2/D8/G10) — the live worker reaches the host over HTTP, and
pointing at a different host is this env var only (no code change)."""
from __future__ import annotations

from rca_agents.config import mcp_host_url


def test_mcp_host_url_default(monkeypatch):
    monkeypatch.delenv("MCP_HOST_URL", raising=False)
    assert mcp_host_url() == "http://127.0.0.1:8100/mcp"


def test_mcp_host_url_env_override(monkeypatch):
    monkeypatch.setenv("MCP_HOST_URL", "http://historian-host:9000/mcp")
    assert mcp_host_url() == "http://historian-host:9000/mcp"
