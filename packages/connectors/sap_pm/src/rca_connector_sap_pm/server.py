"""Wire the SAP PM connector into a FastMCP server with its dependencies."""
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

from .connector import SapNotifications


def make_sap_mcp(
    *,
    http_client: httpx.AsyncClient,
    bindings: dict[tuple[AssetID, str], SourceBinding] | None = None,
    signal_resolver: SignalResolver | None = None,
    source_timezone: str = "UTC",                         # SAP AUSVN is tz-less; interpret in this tz
    retry_attempts: int = 2,
) -> FastMCP:
    resolver = signal_resolver or InMemorySignalResolver({}, bindings or {})
    deps = ToolDeps(
        signal_resolver=resolver,   # asset-scoped: no signals
        config=ToolConfig(source_timezone=source_timezone, retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("sap-pm-connector")
    register(mcp, SapNotifications, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_sap_mcp"]
