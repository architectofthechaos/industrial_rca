"""D14 (Sprint 6 WI2) — failure_modes_for_class returns modes WITH mechanisms.

The FakeToolBox fixture carries real CAUSED_BY mechanism ids from the KG seed
(iso14224_bb1.cypher). McpToolBox delegates to kg.list_failure_modes_for_class.
"""
from rca_agents.toolbox import FakeToolBox


async def test_fake_toolbox_returns_modes_with_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    assert modes, "class should yield failure modes"
    elp = next(m for m in modes if m["code"] == "ELP")
    mech_ids = {x["id"] for x in elp["mechanisms"]}
    assert "failure-mechanism:seal-failure" in mech_ids


async def test_fake_toolbox_vib_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    vib = next(m for m in modes if m["code"] == "VIB")
    mech_ids = {x["id"] for x in vib["mechanisms"]}
    assert "failure-mechanism:cavitation" in mech_ids
    assert "failure-mechanism:misalignment" in mech_ids
    assert "failure-mechanism:bearing-wear" in mech_ids


async def test_fake_toolbox_ohe_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    ohe = next(m for m in modes if m["code"] == "OHE")
    mech_ids = {x["id"] for x in ohe["mechanisms"]}
    assert "failure-mechanism:lubrication-failure" in mech_ids
    assert "failure-mechanism:fouling" in mech_ids
