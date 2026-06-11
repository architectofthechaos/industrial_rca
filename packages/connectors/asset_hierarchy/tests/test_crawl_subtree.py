"""Subtree crawl: descendants only, with ancestors above the root resolved by the
nameFilter walk down from /assetdatabases (site/area WebIds for assets under a unit root).

Includes the tool-level path (asset_hierarchy.crawl_subtree) for the unit root.
"""
from __future__ import annotations

import json

from fake_af import DB_PATH, fake_client, make_fake_af_app, webid
from fastmcp import Client
from rca_contracts import ToolResponse

from rca_connector_asset_hierarchy.crawler import crawl_subtree
from rca_connector_asset_hierarchy.models import CrawlResult
from rca_connector_asset_hierarchy.server import make_asset_hierarchy_mcp

PLANT = "refinery-gc"
SITE_PATH = DB_PATH + "\\SITE-DEMO"
AREA_100_PATH = SITE_PATH + "\\AREA-100"
UNIT_101_PATH = AREA_100_PATH + "\\UNIT-101"
UNIT_102_PATH = AREA_100_PATH + "\\UNIT-102"


async def test_subtree_from_unit_101_returns_its_two_pumps_with_ancestor_ids():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl_subtree(client, root_web_id=webid(UNIT_101_PATH), plant_id=PLANT)
    assert sorted(a.name for a in result.assets) == ["P-101A", "P-101B"]
    for asset in result.assets:
        assert asset.parent_unit_vendor_id == webid(UNIT_101_PATH)
        assert asset.parent_area_vendor_id == webid(AREA_100_PATH)   # ancestor walk
        assert asset.site_vendor_id == webid(SITE_PATH)              # ancestor walk
        assert asset.unit_slug == "unit-101"
    # the root itself is the only hierarchy node (template Unit)
    assert [(n.name, n.kind) for n in result.hierarchy_nodes] == [("UNIT-101", "unit")]
    assert result.hierarchy_nodes[0].vendor_id == webid(UNIT_101_PATH)


async def test_subtree_from_area_100_includes_units_and_the_area_itself():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl_subtree(client, root_web_id=webid(AREA_100_PATH), plant_id=PLANT)
    assert sorted(a.name for a in result.assets) == ["P-101A", "P-101B", "P-102A"]
    nodes = {n.name: n for n in result.hierarchy_nodes}
    assert set(nodes) == {"AREA-100", "UNIT-101", "UNIT-102"}
    assert nodes["AREA-100"].kind == "area"
    assert nodes["UNIT-101"].kind == nodes["UNIT-102"].kind == "unit"
    assert nodes["UNIT-101"].parent_vendor_id == nodes["AREA-100"].vendor_id
    assert nodes["UNIT-102"].parent_vendor_id == nodes["AREA-100"].vendor_id
    p102a = next(a for a in result.assets if a.name == "P-102A")
    assert p102a.parent_unit_vendor_id == nodes["UNIT-102"].vendor_id
    assert p102a.parent_area_vendor_id == nodes["AREA-100"].vendor_id
    assert p102a.site_vendor_id == webid(SITE_PATH)                  # ancestor walk
    assert p102a.proposed_canonical_id == "asset:refinery-gc:unit-102:p-102a"


async def test_tool_crawl_subtree_wraps_result_with_provenance():
    app = make_fake_af_app()
    mcp = make_asset_hierarchy_mcp(http_client_factory=lambda base_url: fake_client(app))
    async with Client(mcp) as c:
        res = await c.call_tool("asset_hierarchy.crawl_subtree", {"request": {
            "base_url": "http://fake-af", "root_web_id": webid(UNIT_101_PATH),
            "plant_id": PLANT}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[CrawlResult].model_validate_json(json.dumps(payload))
        assert resp.error is None, resp.error
        assert resp.provenance is not None
        assert resp.provenance.source == "asset_hierarchy"
        assert resp.provenance.tool_name == "asset_hierarchy.crawl_subtree"
        assert resp.provenance.record_count == 2
        assert sorted(a.name for a in resp.data.assets) == ["P-101A", "P-101B"]


async def test_tool_crawl_subtree_unknown_root_maps_to_not_found():
    app = make_fake_af_app()
    mcp = make_asset_hierarchy_mcp(http_client_factory=lambda base_url: fake_client(app))
    async with Client(mcp) as c:
        res = await c.call_tool("asset_hierarchy.crawl_subtree", {"request": {
            "base_url": "http://fake-af", "root_web_id": "S1bogus", "plant_id": PLANT}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[CrawlResult].model_validate_json(json.dumps(payload))
        assert resp.data is None and resp.error is not None
        assert resp.error.code == "not_found"
