"""Wire the Maximo connector into a FastMCP server with its dependencies."""
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
from rca_contracts import AssetID

from .connector import (
    MaximoCommitWriteback,
    MaximoFailureHistory,
    MaximoPreviewWriteback,
    MaximoWorkOrders,
)

_TOOLS = (MaximoWorkOrders, MaximoFailureHistory, MaximoPreviewWriteback, MaximoCommitWriteback)


def make_maximo_mcp(
    *,
    http_client: httpx.AsyncClient,
    bindings: dict[tuple[AssetID, str], SourceBinding] | None = None,
    signal_resolver: SignalResolver | None = None,
    source_timezone: str = "America/Chicago",             # Maximo emits local-time-without-TZ
    retry_attempts: int = 2,
) -> FastMCP:
    resolver = signal_resolver or InMemorySignalResolver({}, bindings or {})
    deps = ToolDeps(
        signal_resolver=resolver,
        config=ToolConfig(source_timezone=source_timezone, retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("maximo-connector")
    for tool in _TOOLS:
        register(mcp, tool, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_maximo_mcp"]
