"""Wire the OPC UA connector into a FastMCP server with its dependencies."""
from __future__ import annotations

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

from .connector import OpcUaCurrentValue


def make_opcua_mcp(
    *,
    endpoint: str,
    namespace_uri: str,
    signals: dict[SignalID, SignalDescriptor] | None = None,
    bindings: dict[tuple[SignalID, str], SourceBinding] | None = None,   # (signal_id, "opc_ua") -> NodeId string
    signal_resolver: SignalResolver | None = None,
    retry_attempts: int = 2,
) -> FastMCP:
    resolver = signal_resolver or InMemorySignalResolver(signals or {}, bindings or {})
    deps = ToolDeps(
        signal_resolver=resolver,
        config=ToolConfig(endpoint=endpoint, retry_attempts=retry_attempts,
                          extra={"namespace_uri": namespace_uri}),
        http_client=None,                          # OPC UA uses an asyncua client, not httpx
    )
    mcp = build_server("opc-ua-connector")
    register(mcp, OpcUaCurrentValue, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_opcua_mcp"]
