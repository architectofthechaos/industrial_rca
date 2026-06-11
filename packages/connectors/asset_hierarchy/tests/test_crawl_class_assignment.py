"""ISO 14224 class assignment (spec §2.3): template rule beats tag rule on confidence.

P-101A matches BOTH rule:pump_template_name (template, 0.95) and rule:pump_p_tag
(tag, 0.85); the crawler must report the higher-confidence template match.
"""
from __future__ import annotations

from fake_af import DB_NAME, fake_client, make_fake_af_app

from rca_connector_asset_hierarchy.crawler import crawl

PLANT = "refinery-gc"


async def test_p101a_classified_by_the_template_rule():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    pump = next(a for a in result.assets if a.name == "P-101A")
    assert pump.iso14224_class == "pump.centrifugal"
    assert pump.iso14224_class_method == "rule:pump_template_name"
    assert pump.iso14224_class_confidence >= 0.95


async def test_every_refplant_pump_gets_the_template_rule_class():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    assert len(result.assets) == 4
    for asset in result.assets:
        assert asset.iso14224_class == "pump.centrifugal"
        assert asset.iso14224_class_method == "rule:pump_template_name"


async def test_asset_attributes_are_flat_string_maps():
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    pump = next(a for a in result.assets if a.name == "P-101A")
    assert pump.attributes["Manufacturer"] == "Sulzer"
    assert pump.attributes["Model"] == "AHLSTAR-A22-50"
    assert pump.attributes["SerialNumber"] == "SN-2018-00471"
    assert pump.attributes["Criticality"] == "high"
    assert pump.attributes["ISO14224Class"] == "pump.centrifugal"
    assert pump.attributes["ServiceDescription"] == "charge pump"
    assert all(isinstance(v, str) for v in pump.attributes.values())
