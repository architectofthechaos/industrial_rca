"""S2.5 — OPC UA address-space mapping tests (pure, no server).

The node plan mirrors the plant hierarchy (Site/Area/Unit/Asset/Signal) and maps
deterministically to fixture signals.
"""
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.opcua.address_space import build_node_plan

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"


def plans():
    return build_node_plan(load(REFPLANT))


def test_one_node_per_signal():
    rp = load(REFPLANT)
    p = build_node_plan(rp)
    assert len(p) == len(rp.signals)
    assert {n.signal_key for n in p} == set(rp.signals)


def test_browse_path_mirrors_plant_hierarchy():
    by_key = {n.signal_key: n for n in plans()}
    node = by_key["P-101A.discharge_pressure"]
    assert node.browse_path == (
        "SITE-DEMO", "AREA-100", "UNIT-101", "P-101A", "discharge_pressure",
    )


def test_identifiers_unique_and_stable():
    p1 = [n.identifier for n in plans()]
    p2 = [n.identifier for n in plans()]
    assert len(set(p1)) == len(p1)      # unique
    assert p1 == p2                     # deterministic ordering


def test_node_plan_follows_plant_then_role_order():
    p = plans()
    # P-101A (UNIT-101) appears before P-103A (UNIT-201, different area)
    a_idx = next(i for i, n in enumerate(p) if n.browse_path[3] == "P-101A")
    d_idx = next(i for i, n in enumerate(p) if n.browse_path[3] == "P-103A")
    assert a_idx < d_idx
