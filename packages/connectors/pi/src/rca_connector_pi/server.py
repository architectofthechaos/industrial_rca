"""Wire the PI connector into a FastMCP server with its dependencies."""
from __future__ import annotations

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    InMemorySignalResolver,
    SignalResolver,
    SourceBinding,
    ToolConfig,
    ToolDeps,
    build_server,
    register,
)
from rca_contracts import SignalDescriptor, SignalID

from .connector import PiEventFrames, PiSeries, PiSummary


def make_pi_mcp(
    *,
    http_client: httpx.AsyncClient,
    signals: dict[SignalID, SignalDescriptor] | None = None,
    bindings: dict[tuple[SignalID, str], SourceBinding] | None = None,
    signal_resolver: SignalResolver | None = None,
    source_timezone: str = "UTC",
    retry_attempts: int = 2,
) -> FastMCP:
    resolver = signal_resolver or InMemorySignalResolver(signals or {}, bindings or {})
    deps = ToolDeps(
        signal_resolver=resolver,
        config=ToolConfig(source_timezone=source_timezone, retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("pi-connector")
    for tool in (PiSeries, PiSummary, PiEventFrames):
        register(mcp, tool, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_pi_mcp"]
