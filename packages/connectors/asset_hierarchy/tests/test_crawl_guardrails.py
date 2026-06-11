"""Crawler guardrails: non-hierarchy ancestors fail loud; max_depth skips deep elements.

An element nested under another ASSET (M-101A under P-101A, depth 5) must raise
MalformedResponse from the pure crawler — and surface as a validation_failed ToolError
at the tool boundary — rather than silently recording the parent asset as its unit.
max_depth=3 keeps Site/Area/Unit but skips the depth-4 assets; the default (6) is
unchanged.
"""
from __future__ import annotations

import json

import pytest
from fake_af import DB_NAME, fake_client, make_fake_af_app
from fastmcp import Client
from rca_connector_sdk import MalformedResponse
from rca_contracts import ToolResponse

from rca_connector_asset_hierarchy.crawler import crawl
from rca_connector_asset_hierarchy.models import CrawlResult
from rca_connector_asset_hierarchy.server import make_asset_hierarchy_mcp

PLANT = "refinery-gc"


async def test_asset_nested_under_asset_raises_malformed_response():
    async with fake_client(make_fake_af_app(include_nested_child=True)) as client:
        with pytest.raises(MalformedResponse, match="M-101A"):
            await crawl(client, database_name=DB_NAME, plant_id=PLANT)


async def test_tool_crawl_maps_nested_asset_child_to_validation_failed():
    app = make_fake_af_app(include_nested_child=True)
    mcp = make_asset_hierarchy_mcp(http_client_factory=lambda base_url: fake_client(app))
    async with Client(mcp) as c:
        res = await c.call_tool("asset_hierarchy.crawl", {"request": {
            "base_url": "http://fake-af", "database_name": DB_NAME, "plant_id": PLANT}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[CrawlResult].model_validate_json(json.dumps(payload))
        assert resp.data is None and resp.error is not None
        assert resp.error.code == "validation_failed"
        assert "M-101A" in resp.error.message


async def test_max_depth_3_skips_assets_but_keeps_the_full_hierarchy():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT, max_depth=3)
    assert result.assets == []                          # assets sit at depth 4
    assert sorted(n.kind for n in result.hierarchy_nodes) == \
        ["area", "area", "site", "unit", "unit", "unit"]


async def test_explicit_max_depth_6_matches_the_default():
    async with fake_client(make_fake_af_app()) as client:
        default = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    async with fake_client(make_fake_af_app()) as client:
        explicit = await crawl(client, database_name=DB_NAME, plant_id=PLANT, max_depth=6)
    assert explicit == default
    assert sorted(a.name for a in explicit.assets) == ["P-101A", "P-101B", "P-102A", "P-103A"]
