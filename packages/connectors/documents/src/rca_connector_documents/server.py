"""Wire the Documents connector (SharePoint/HTTP backend) into a FastMCP server."""
from __future__ import annotations

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    InMemorySignalResolver,
    ToolConfig,
    ToolDeps,
    build_server,
    register,
)

from .connector import DocumentsFetch, DocumentsSearch


def make_documents_mcp(*, http_client: httpx.AsyncClient, retry_attempts: int = 2) -> FastMCP:
    deps = ToolDeps(
        signal_resolver=InMemorySignalResolver({}),   # query-scoped: resolver is unused
        config=ToolConfig(retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("documents-connector")
    for tool in (DocumentsSearch, DocumentsFetch):
        register(mcp, tool, deps)  # type: ignore[arg-type]
    return mcp


__all__ = ["make_documents_mcp"]
