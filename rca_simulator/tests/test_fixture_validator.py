"""S2.1 — fixture validator tests (SPEC-014 referential-integrity rules).

The golden reference fixture validates clean; each deliberately-broken variant
fails with a specific, named error code.
"""
from datetime import timedelta
from pathlib import Path

import pytest

from rca_simulator.fixtures.loader import load
from rca_simulator.fixtures.schema import SignalTrajectory
from rca_simulator.fixtures._validate import (
    FixtureValidationError,
    validate,
    validate_or_raise,
)

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"


def good():
    return load(REFPLANT)


def codes(refplant):
    return {v.code for v in validate(refplant)}


# ---------- golden passes ----------

def test_reference_fixture_is_clean():
    assert validate(good()) == []
    validate_or_raise(good())  # must not raise


# ---------- 12 broken variants, each a named error ----------

def test_v01_plant_references_unknown_asset():
    rp = good()
    rp.plant.site.areas[0].units[0].equipment[0].asset_ref = "P-999X"
    assert "ASSET_REF_UNRESOLVED" in codes(rp)


def test_v02_signal_references_unknown_asset():
    rp = good()
    rp.signals["P-101A.discharge_pressure"].asset_ref = "P-999X"
    assert "SIGNAL_ASSET_MISSING" in codes(rp)


def test_v03_signal_role_not_in_template():
    rp = good()
    rp.signals["P-101A.discharge_pressure"].role = "bogus_role"
    assert "SIGNAL_ROLE_NOT_IN_TEMPLATE" in codes(rp)


def test_v04_signal_units_not_valid_qudt():
    rp = good()
    rp.signals["P-101A.discharge_pressure"].canonical_units = "FURLONGS"
    assert "UNIT_NOT_QUDT" in codes(rp)


def test_v05_signal_units_mismatch_template():
    rp = good()
    # bearing_temp_de must be DEG_C per template; kPa is a valid QUDT unit but wrong here
    rp.signals["P-101A.bearing_temp_de"].canonical_units = "kPa"
    assert "SIGNAL_UNITS_MISMATCH_TEMPLATE" in codes(rp)


def test_v06_scenario_affected_asset_unknown():
    rp = good()
    rp.scenarios["seal_leak_progression"].affected_asset = "P-999X"
    assert "SCENARIO_ASSET_MISSING" in codes(rp)


def test_v07_scenario_role_missing_for_asset():
    rp = good()
    # P-101A has no 'flow' signal, though 'flow' is a valid template role
    rp.scenarios["seal_leak_progression"].signal_trajectories.append(
        SignalTrajectory(role="flow", trajectory="linear_growth", end_offset=10)
    )
    assert "SCENARIO_ROLE_MISSING_FOR_ASSET" in codes(rp)


def test_v08_scenario_event_references_unknown_signal():
    rp = good()
    for ev in rp.scenarios["seal_leak_progression"].events:
        if ev.type == "alarm":
            ev.payload["signal"] = "P-101A.nonexistent_signal"
    assert "EVENT_SIGNAL_UNKNOWN" in codes(rp)


def test_v09_two_scenarios_overlap_same_asset():
    rp = good()
    base = rp.scenarios["seal_leak_progression"]
    clash = base.model_copy(deep=True)
    clash.scenario_id = "seal_leak_progression_dup"
    clash.t0 = base.t0 + timedelta(days=5)  # overlaps the 30-day window
    clash.duration_days = 5
    rp.scenarios[clash.scenario_id] = clash
    assert "SCENARIO_OVERLAP" in codes(rp)


def test_v10_scenario_runs_past_window_end():
    rp = good()
    rp.scenarios["seal_leak_progression"].duration_days = 400  # past window_end
    assert "SCENARIO_OUT_OF_BOUNDS" in codes(rp)


def test_v11_scenario_starts_before_window_start():
    rp = good()
    ta = rp.time_axis
    rp.scenarios["seal_leak_progression"].t0 = ta.window_start - timedelta(days=10)
    assert "SCENARIO_OUT_OF_BOUNDS" in codes(rp)


def test_v12_disjoint_scenarios_same_asset_do_not_overlap():
    # Negative control for the overlap rule: same asset, non-overlapping windows is OK.
    rp = good()
    base = rp.scenarios["seal_leak_progression"]  # P-101A, ends day 30
    later = base.model_copy(deep=True)
    later.scenario_id = "seal_leak_later"
    later.t0 = base.t0 + timedelta(days=60)
    later.duration_days = 5
    rp.scenarios[later.scenario_id] = later
    assert "SCENARIO_OVERLAP" not in codes(rp)


# ---------- raising API ----------

def test_validate_or_raise_reports_codes():
    rp = good()
    rp.scenarios["seal_leak_progression"].affected_asset = "P-999X"
    with pytest.raises(FixtureValidationError) as exc:
        validate_or_raise(rp)
    assert any(v.code == "SCENARIO_ASSET_MISSING" for v in exc.value.violations)
