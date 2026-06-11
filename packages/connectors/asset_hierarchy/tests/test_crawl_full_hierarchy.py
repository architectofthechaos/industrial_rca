"""Full-database crawl: 4 refplant assets + 6 hierarchy nodes, correct parent wiring.

Hermetic against fake_af; the live test re-runs the crawl against the REAL PI simulator
(skip-if-unreachable, `task parity:asset_hierarchy`) and must mint the same canonical ids.
"""
from __future__ import annotations

import json
import os
import re

import httpx
import pytest
from fake_af import DB_NAME, fake_client, make_fake_af_app
from fastmcp import Client
from rca_contracts import ToolResponse

from rca_connector_asset_hierarchy.crawler import crawl
from rca_connector_asset_hierarchy.models import CrawlResult
from rca_connector_asset_hierarchy.server import make_asset_hierarchy_mcp

PLANT = "refinery-gc"
PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://localhost:8001")
CANONICAL_RE = r"^asset:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$"
EXPECTED = {
    "P-101A": ("unit-101", "asset:refinery-gc:unit-101:p-101a", "UNIT-101", "AREA-100"),
    "P-101B": ("unit-101", "asset:refinery-gc:unit-101:p-101b", "UNIT-101", "AREA-100"),
    "P-102A": ("unit-102", "asset:refinery-gc:unit-102:p-102a", "UNIT-102", "AREA-100"),
    "P-103A": ("unit-201", "asset:refinery-gc:unit-201:p-103a", "UNIT-201", "AREA-200"),
}


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{PI_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


async def _crawl_fake() -> CrawlResult:
    async with fake_client(make_fake_af_app()) as client:
        return await crawl(client, database_name=DB_NAME, plant_id=PLANT)


async def test_full_crawl_discovers_exactly_the_four_refplant_assets():
    result = await _crawl_fake()
    assert sorted(a.name for a in result.assets) == ["P-101A", "P-101B", "P-102A", "P-103A"]
    by_name = {a.name: a for a in result.assets}
    for name, (unit_slug, canonical_id, _unit, _area) in EXPECTED.items():
        asset = by_name[name]
        assert asset.unit_slug == unit_slug
        assert re.match(CANONICAL_RE, asset.proposed_canonical_id)
        assert asset.proposed_canonical_id == canonical_id
        assert asset.plant_id == PLANT
        assert asset.vendor_id and asset.vendor_id.startswith("S1")
        assert asset.vendor_path.startswith("\\\\PI-DEMO\\Refinery-GC\\")
    assert by_name["P-101A"].vendor_path == \
        "\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO\\AREA-100\\UNIT-101\\P-101A"


async def test_hierarchy_nodes_are_one_site_two_areas_three_units_with_parent_wiring():
    result = await _crawl_fake()
    by_kind: dict[str, list] = {"site": [], "area": [], "unit": []}
    for node in result.hierarchy_nodes:
        by_kind[node.kind].append(node)
    assert [len(by_kind["site"]), len(by_kind["area"]), len(by_kind["unit"])] == [1, 2, 3]
    by_name = {n.name: n for n in result.hierarchy_nodes}
    site = by_name["SITE-DEMO"]
    assert site.parent_vendor_id is None
    assert site.plant_id == PLANT
    assert all(n.vendor_id and n.vendor_id.startswith("S1") for n in result.hierarchy_nodes)
    for area in ("AREA-100", "AREA-200"):
        assert by_name[area].parent_vendor_id == site.vendor_id
    assert by_name["UNIT-101"].parent_vendor_id == by_name["AREA-100"].vendor_id
    assert by_name["UNIT-102"].parent_vendor_id == by_name["AREA-100"].vendor_id
    assert by_name["UNIT-201"].parent_vendor_id == by_name["AREA-200"].vendor_id
    # every asset's parent vendor ids point at the corresponding hierarchy nodes
    for asset in result.assets:
        _slug, _cid, unit, area = EXPECTED[asset.name]
        assert asset.parent_unit_vendor_id == by_name[unit].vendor_id
        assert asset.parent_area_vendor_id == by_name[area].vendor_id
        assert asset.site_vendor_id == site.vendor_id


async def test_tool_crawl_returns_toolresponse_with_asset_hierarchy_provenance():
    app = make_fake_af_app()
    mcp = make_asset_hierarchy_mcp(http_client_factory=lambda base_url: fake_client(app))
    async with Client(mcp) as c:
        res = await c.call_tool("asset_hierarchy.crawl", {"request": {
            "base_url": "http://fake-af", "database_name": DB_NAME, "plant_id": PLANT}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[CrawlResult].model_validate_json(json.dumps(payload))
        assert resp.error is None, resp.error
        assert resp.provenance is not None
        assert resp.provenance.source == "asset_hierarchy"
        assert resp.provenance.tool_name == "asset_hierarchy.crawl"
        assert resp.provenance.record_count == 4
        assert "elements" in resp.provenance.source_query
        assert len(resp.data.assets) == 4 and len(resp.data.hierarchy_nodes) == 6


async def test_tool_crawl_unknown_database_maps_to_not_found():
    app = make_fake_af_app()
    mcp = make_asset_hierarchy_mcp(http_client_factory=lambda base_url: fake_client(app))
    async with Client(mcp) as c:
        res = await c.call_tool("asset_hierarchy.crawl", {"request": {
            "base_url": "http://fake-af", "database_name": "No-Such-DB", "plant_id": PLANT}})
        payload = res.structured_content if res.structured_content is not None else res.data
        resp = ToolResponse[CrawlResult].model_validate_json(json.dumps(payload))
        assert resp.data is None and resp.error is not None
        assert resp.error.code == "not_found"


@pytest.mark.skipif(not _sim_reachable(),
                    reason=f"PI simulator not reachable at {PI_SIM_URL}"
                           " (run `task parity:asset_hierarchy`)")
async def test_live_sim_crawl_mints_the_same_four_canonical_ids():
    async with httpx.AsyncClient(base_url=PI_SIM_URL, timeout=10.0) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    assert {a.proposed_canonical_id for a in result.assets} == {
        canonical for _slug, canonical, _unit, _area in EXPECTED.values()}
    kinds = sorted(n.kind for n in result.hierarchy_nodes)
    assert kinds == ["area", "area", "site", "unit", "unit", "unit"]
