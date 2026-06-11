"""FastMCP server for the asset_hierarchy crawler tools (Sprint 2a Task 7).

Hand-wired tools in the MAR/KG-server style (ok_response + map_source_error
+ ToolResponse[CrawlResult]) — NOT @evidence_tool, because base_url arrives per
request: each call opens its own httpx.AsyncClient (factory injectable for tests),
runs the pure crawler, and wraps the result with source="asset_hierarchy" provenance.
source_query records the elements listing URL (the full crawl shows the database by
name, since its WebId is internal to the crawler).
"""
from __future__ import annotations

from collections.abc import Callable

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import build_server, map_source_error, ok_response, register_health
from rca_contracts import ToolResponse

from . import crawler
from .health import AssetHierarchyHealthProbe, _default_factory as _health_default_factory
from .models import CrawlRequest, CrawlResult, CrawlSubtreeRequest

_VERSION = "0.1.0"
_SOURCE = "asset_hierarchy"
_LISTING = "elements?searchFullHierarchy=true&maxCount=10000"


def _default_factory(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def make_asset_hierarchy_mcp(
    *,
    http_client_factory: Callable[[str], httpx.AsyncClient] | None = None,
    default_base_url: str | None = None,
) -> FastMCP:
    factory = http_client_factory or _default_factory
    mcp = build_server("asset_hierarchy")
    register_health(
        mcp,
        version=_VERSION,
        probe=AssetHierarchyHealthProbe(_health_default_factory, default_base_url=default_base_url),
    )

    @mcp.tool(name="asset_hierarchy.crawl")
    async def crawl(request: CrawlRequest) -> ToolResponse[CrawlResult]:
        envelope = ToolResponse[CrawlResult]
        try:
            async with factory(request.base_url) as client:
                result = await crawler.crawl(
                    client, database_name=request.database_name,
                    plant_id=request.plant_id, max_depth=request.max_depth)
            return ok_response(result, tool="asset_hierarchy.crawl",
                               version=_VERSION, source=_SOURCE,
                               source_query=(f"{request.base_url}/assetdatabases"
                                             f"/<{request.database_name}>/{_LISTING}"),
                               record_count=len(result.assets),
                               raw_tags=[a.name for a in result.assets])
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="asset_hierarchy.crawl_subtree")
    async def crawl_subtree(request: CrawlSubtreeRequest) -> ToolResponse[CrawlResult]:
        envelope = ToolResponse[CrawlResult]
        try:
            async with factory(request.base_url) as client:
                result = await crawler.crawl_subtree(
                    client, root_web_id=request.root_web_id,
                    plant_id=request.plant_id, max_depth=request.max_depth)
            return ok_response(result, tool="asset_hierarchy.crawl_subtree",
                               version=_VERSION, source=_SOURCE,
                               source_query=(f"{request.base_url}/elements"
                                             f"/{request.root_web_id}/{_LISTING}"),
                               record_count=len(result.assets),
                               raw_tags=[a.name for a in result.assets])
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


__all__ = ["make_asset_hierarchy_mcp"]
