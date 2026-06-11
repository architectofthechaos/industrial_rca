"""Wire the Documents connector (SharePoint/HTTP backend) into a FastMCP server."""
from __future__ import annotations

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    InMemoryTagResolver,
    ToolConfig,
    ToolDeps,
    build_server,
    register,
    register_health,
)

from .connector import DocumentsFetch, DocumentsSearch
from .health import ClientFactory, DocumentsHealthProbe, _default_factory

_VERSION = "0.1.0"


def make_documents_mcp(
    *,
    http_client: httpx.AsyncClient,
    retry_attempts: int = 2,
    health_client_factory: ClientFactory | None = None,  # inject for tests
) -> FastMCP:
    deps = ToolDeps(
        tag_resolver=InMemoryTagResolver({}),   # query-scoped: resolver is unused
        config=ToolConfig(retry_attempts=retry_attempts),
        http_client=http_client,
    )
    mcp = build_server("documents-connector")
    for tool in (DocumentsSearch, DocumentsFetch):
        register(mcp, tool, deps)  # type: ignore[arg-type]
    configured_base_url = str(http_client.base_url)
    factory = health_client_factory or _default_factory(configured_base_url)
    register_health(mcp, version=_VERSION, probe=DocumentsHealthProbe(factory))
    return mcp


__all__ = ["make_documents_mcp"]
