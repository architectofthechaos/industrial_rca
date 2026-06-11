"""vendor_id stability: WebIds are deterministic functions of the AF path, so two
separately constructed fakes ("restarts") and a local re-encoding of the path must
agree — mirroring the real simulator's deterministic WebId scheme.
"""
from __future__ import annotations

import base64

from fake_af import DB_NAME, fake_client, make_fake_af_app

from rca_connector_asset_hierarchy.crawler import crawl
from rca_connector_asset_hierarchy.models import CrawlResult

PLANT = "refinery-gc"


async def _crawl_fresh_app() -> CrawlResult:
    async with fake_client(make_fake_af_app()) as client:
        return await crawl(client, database_name=DB_NAME, plant_id=PLANT)


async def test_two_separately_constructed_apps_yield_identical_vendor_ids():
    first = await _crawl_fresh_app()
    second = await _crawl_fresh_app()
    assert {a.name: a.vendor_id for a in first.assets} == \
        {a.name: a.vendor_id for a in second.assets}
    assert {n.name: n.vendor_id for n in first.hierarchy_nodes} == \
        {n.name: n.vendor_id for n in second.hierarchy_nodes}


async def test_vendor_id_is_the_webid_of_the_vendor_path():
    # proves the scheme itself is stable: vendor_id == "S1" + urlsafe_b64(path), unpadded
    result = await _crawl_fresh_app()
    everything = [(a.vendor_id, a.vendor_path) for a in result.assets]
    everything += [(n.vendor_id, n.vendor_path) for n in result.hierarchy_nodes]
    assert len(everything) == 10  # 4 assets + 6 hierarchy nodes
    for vendor_id, vendor_path in everything:
        expected = "S1" + base64.urlsafe_b64encode(vendor_path.encode()).decode().rstrip("=")
        assert vendor_id == expected
