"""S2.1 — fixture loader tests.

The loader parses fixtures/refplant/ into a fully-typed RefPlant object graph
and raises (never returns partial data) on missing/invalid input.
"""
from pathlib import Path

import pytest

from rca_simulator.fixtures.loader import load
from rca_simulator.fixtures.schema import RefPlant

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"


def test_loads_refplant_object_graph():
    rp = load(REFPLANT)
    assert isinstance(rp, RefPlant)
    assert rp.fixture_version == "1.0.0"
    assert set(rp.assets) == {"P-101A", "P-101B", "P-102A", "P-103A"}
    assert len(rp.signals) == 21
    assert set(rp.scenarios) == {
        "seal_leak_progression", "cavitation_event",
        "bearing_failure", "motor_trip_overload",
    }


def test_signals_keyed_by_tag_and_role():
    rp = load(REFPLANT)
    sig = rp.signals["P-101A.discharge_pressure"]
    assert sig.asset_ref == "P-101A"
    assert sig.role == "discharge_pressure"
    assert sig.canonical_units == "kPa"
    assert "P-101A.seal_flush_flow" in rp.signals


def test_time_axis_and_work_orders_loaded():
    rp = load(REFPLANT)
    assert rp.time_axis.clock_skews["maximo"] == 1.5
    seeded = [wo["wo_number"] for seed in rp.work_orders for wo in seed.work_orders]
    assert "WO-49900001" in seeded


def test_load_accepts_str_path():
    rp = load(str(REFPLANT))
    assert isinstance(rp, RefPlant)


def test_missing_directory_raises():
    with pytest.raises(FileNotFoundError):
        load(REFPLANT.parent / "does_not_exist")
