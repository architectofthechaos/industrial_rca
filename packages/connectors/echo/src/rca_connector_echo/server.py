"""Wire the echo connector into a FastMCP server with its dependencies."""
from __future__ import annotations

from uuid import UUID

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    InMemoryTagResolver,
    SourceBinding,
    ToolConfig,
    ToolDeps,
    build_server,
    register,
)
from rca_contracts import TagDescriptor

from .connector import EchoSeries


def make_echo_mcp(
    *,
    http_client: httpx.AsyncClient,
    signals: dict[UUID, TagDescriptor],
    raw_unit: str = "bar",
    source_timezone: str = "UTC",
    retry_attempts: int = 2,
) -> FastMCP:
    bindings = {
        (sid, "echo"): SourceBinding(handle=str(sid), raw_unit=raw_unit)
        for sid in signals
    }
    deps = ToolDeps(
        tag_resolver=InMemoryTagResolver(signals, bindings),
        config=ToolConfig(source_timezone=source_timezone, retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("echo-connector")
    # EchoSeries is an EvidenceTool at runtime (class decorator); mypy keeps the class type
    register(mcp, EchoSeries, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_echo_mcp"]
