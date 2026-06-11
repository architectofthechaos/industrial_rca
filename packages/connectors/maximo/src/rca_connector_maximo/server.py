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
    register_health,
)
from rca_contracts import AssetID

from .connector import (
    MaximoCommitWriteback,
    MaximoFailureHistory,
    MaximoPreviewWriteback,
    MaximoWorkOrders,
)
from .health import ClientFactory, MaximoHealthProbe, _default_factory

_TOOLS = (MaximoWorkOrders, MaximoFailureHistory, MaximoPreviewWriteback, MaximoCommitWriteback)
_VERSION = "0.1.0"


def make_maximo_mcp(
    *,
    http_client: httpx.AsyncClient,
    bindings: dict[tuple[AssetID, str], SourceBinding] | None = None,
    signal_resolver: SignalResolver | None = None,
    source_timezone: str = "America/Chicago",             # Maximo emits local-time-without-TZ
    retry_attempts: int = 2,
    health_client_factory: ClientFactory | None = None,  # inject for tests
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
    configured_base_url = str(http_client.base_url)
    factory = health_client_factory or _default_factory(configured_base_url)
    register_health(mcp, version=_VERSION, probe=MaximoHealthProbe(factory))
    return mcp


__all__ = ["make_maximo_mcp"]
