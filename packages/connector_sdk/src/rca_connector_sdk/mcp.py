"""FastMCP server skeleton + evidence-tool registration (ADR-0005).

`build_server` creates the connector's MCP server; `register` binds an EvidenceTool
to its deps and exposes it as an MCP tool with the request model as input schema and
a ToolResponse[T] return. (Tier-aware catalog filtering is a later concern.)
"""
from __future__ import annotations

from fastmcp import FastMCP
from rca_contracts import ToolResponse

from .context import ToolDeps
from .orchestrator import EvidenceTool


def build_server(name: str) -> FastMCP:
    return FastMCP(name)


def register(mcp: FastMCP, tool: EvidenceTool, deps: ToolDeps) -> None:
    """Register `tool` (bound to `deps`) on `mcp` under its catalog name."""
    run = tool.bind(deps)
    meta = tool.meta

    async def handler(request):  # noqa: ANN001 — annotations set dynamically below
        return await run(request)

    handler.__name__ = meta.name.replace(".", "_")
    handler.__annotations__ = {
        "request": meta.request,
        "return": ToolResponse[meta.response],  # type: ignore[name-defined]  # runtime-parametrized
    }
    mcp.tool(name=meta.name)(handler)


__all__ = ["build_server", "register"]
