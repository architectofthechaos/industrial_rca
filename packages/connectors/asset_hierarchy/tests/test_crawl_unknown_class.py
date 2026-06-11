"""Unknown-template elements stay honest: class None, confidence 0.0, method "none"."""
from __future__ import annotations

from fake_af import DB_NAME, fake_client, make_fake_af_app

from rca_connector_asset_hierarchy.crawler import crawl

PLANT = "refinery-gc"


async def test_mystery_element_has_no_class_and_method_none():
    async with fake_client(make_fake_af_app(include_mystery=True)) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    assert sorted(a.name for a in result.assets) == [
        "MYSTERY-1", "P-101A", "P-101B", "P-102A", "P-103A"]
    mystery = next(a for a in result.assets if a.name == "MYSTERY-1")
    assert mystery.iso14224_class is None
    assert mystery.iso14224_class_confidence == 0.0
    assert mystery.iso14224_class_method == "none"
    # it still gets full hierarchy wiring under UNIT-102
    unit_102 = next(n for n in result.hierarchy_nodes if n.name == "UNIT-102")
    assert mystery.parent_unit_vendor_id == unit_102.vendor_id
    assert mystery.unit_slug == "unit-102"
    assert mystery.proposed_canonical_id == "asset:refinery-gc:unit-102:mystery-1"
