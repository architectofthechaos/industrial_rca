"""Wire the PI connector into a FastMCP server with its dependencies."""
from __future__ import annotations

from uuid import UUID

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    InMemoryTagResolver,
    SourceBinding,
    TagResolver,
    ToolConfig,
    ToolDeps,
    build_server,
    register,
    register_health,
)
from rca_contracts import TagDescriptor

from .connector import PiEventFrames, PiSeries, PiSummary
from .health import ClientFactory, PiHealthProbe, _default_factory

_VERSION = "0.1.0"


def make_pi_mcp(
    *,
    http_client: httpx.AsyncClient,
    signals: dict[UUID, TagDescriptor] | None = None,
    bindings: dict[tuple[UUID, str], SourceBinding] | None = None,
    tag_resolver: TagResolver | None = None,
    source_timezone: str = "UTC",
    retry_attempts: int = 2,
    health_client_factory: ClientFactory | None = None,   # inject for tests
) -> FastMCP:
    resolver = tag_resolver or InMemoryTagResolver(signals or {}, bindings or {})
    deps = ToolDeps(
        tag_resolver=resolver,
        config=ToolConfig(source_timezone=source_timezone, retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("pi-connector")
    for tool in (PiSeries, PiSummary, PiEventFrames):
        register(mcp, tool, deps)  # type: ignore[arg-type]
    configured_base_url = str(http_client.base_url)
    factory = health_client_factory or _default_factory(configured_base_url)
    register_health(mcp, version=_VERSION, probe=PiHealthProbe(factory))
    return mcp


__all__ = ["make_pi_mcp"]
