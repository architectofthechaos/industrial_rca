"""Wire the OPC UA connector into a FastMCP server with its dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

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

from .connector import OpcUaCurrentValue
from .health import OpcUaHealthProbe

_VERSION = "0.1.0"


def make_opcua_mcp(
    *,
    endpoint: str,
    namespace_uri: str,
    signals: dict[UUID, TagDescriptor] | None = None,
    bindings: dict[tuple[UUID, str], SourceBinding] | None = None,   # (signal_id, "opc_ua") -> NodeId string
    tag_resolver: TagResolver | None = None,
    retry_attempts: int = 2,
    opcua_health_factory: Callable[[str], Any] | None = None,            # inject a fake for tests
) -> FastMCP:
    resolver = tag_resolver or InMemoryTagResolver(signals or {}, bindings or {})
    deps = ToolDeps(
        tag_resolver=resolver,
        config=ToolConfig(endpoint=endpoint, retry_attempts=retry_attempts,
                          extra={"namespace_uri": namespace_uri}),
        http_client=None,                          # OPC UA uses an asyncua client, not httpx
    )
    mcp = build_server("opc-ua-connector")
    register(mcp, OpcUaCurrentValue, deps)  # type: ignore[arg-type]
    register_health(mcp, version=_VERSION,
                    probe=OpcUaHealthProbe(endpoint, opcua_client_factory=opcua_health_factory))
    return mcp


__all__ = ["make_opcua_mcp"]
