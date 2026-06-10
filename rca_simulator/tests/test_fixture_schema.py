"""S2.1 — fixture Pydantic schema tests (per SPEC-014).

Pure model tests: validate well-formed dicts parse, malformed ones raise,
timestamps are tz-aware, and unknown fields are rejected (catches typos).
"""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from rca_simulator.fixtures.schema import (
    Asset,
    Plant,
    Scenario,
    Signal,
    TimeAxis,
)


def test_plant_parses_nested_hierarchy():
    plant = Plant.model_validate(
        {
            "version": 1,
            "site": {
                "site_id": "SITE-DEMO",
                "name": "Demo Refinery",
                "timezone": "America/Chicago",
                "areas": [
                    {
                        "area_id": "AREA-100",
                        "name": "Crude Unit",
                        "units": [
                            {
                                "unit_id": "UNIT-101",
                                "name": "Crude Distillation",
                                "equipment": [{"asset_ref": "P-101A"}],
                            }
                        ],
                    }
                ],
            },
        }
    )
    assert plant.site.areas[0].units[0].equipment[0].asset_ref == "P-101A"


def _asset_dict(**overrides):
    base = {
        "version": 1,
        "asset_id_seed": "0190d3c9-0000-7000-8000-000000000001",
        "external_ids": {"maximo_location": "CRDU-P101A"},
        "tag": "P-101A",
        "service": "charge pump",
        "iso14224_class": "pump.centrifugal",
        "nameplate": {
            "manufacturer": "Sulzer",
            "model": "AHLSTAR-A22-50",
            "serial": "SN-2018-00471",
            "rated_flow_m3h": 320,
            "rated_head_m": 145,
            "rated_speed_rpm": 3550,
            "rated_power_kw": 185,
        },
        "parent_unit": "UNIT-101",
        "criticality": "high",
        "installed_at": "2018-06-12",
        "template_class": "centrifugal_pump",
        "template_version": "v0.3.1",
    }
    base.update(overrides)
    return base


def test_asset_parses_and_coerces_date():
    asset = Asset.model_validate(_asset_dict())
    assert asset.tag == "P-101A"
    assert asset.installed_at == date(2018, 6, 12)
    assert asset.nameplate.rated_power_kw == 185


def test_asset_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Asset.model_validate(_asset_dict(typo_field="oops"))


def _signal_dict(**overrides):
    base = {
        "version": 1,
        "asset_ref": "P-101A",
        "role": "discharge_pressure",
        "display_name": "P-101A Discharge Pressure",
        "source_systems": [
            {"source": "pi", "raw_tag": "PUMP_101A.DISCH_P", "units_raw": "psig"}
        ],
        "canonical_units": "kPa",
        "qudt_quantity_kind": "Pressure",
        "sampling": {"expected_hz": 1.0, "stored_compression_deviation": 0.5},
        "range": {
            "operating_min": 800,
            "operating_max": 2000,
            "alarm_lo": 600,
            "alarm_hi": 2400,
        },
        "baseline": {"mean": 1450, "stddev": 35, "diurnal_amplitude": 25},
    }
    base.update(overrides)
    return base


def test_signal_parses():
    sig = Signal.model_validate(_signal_dict())
    assert sig.role == "discharge_pressure"
    assert sig.canonical_units == "kPa"
    assert sig.baseline.mean == 1450
    assert sig.source_systems[0].source == "pi"


def _scenario_dict(**overrides):
    base = {
        "version": 1,
        "scenario_id": "seal_leak_progression",
        "description": "Slow seal degradation",
        "affected_asset": "P-101A",
        "failure_mode_iso14224": "LEK",
        "duration_days": 30,
        "t0": "2026-03-01T00:00:00Z",
        "signal_trajectories": [
            {"role": "discharge_pressure", "trajectory": "linear_decay",
             "start_offset": 0, "end_offset": -180},
            {"role": "vibration_radial", "trajectory": "step_then_growth",
             "steps": [{"at_day": 18, "offset": 1.2}, {"at_day": 25, "offset": 4.5}]},
        ],
        "events": [
            {"at_day": 18, "type": "work_order", "sink": "maximo",
             "payload": {"wo_number": "WO-50012345"}},
        ],
        "expected_rca": {
            "primary_failure_mode": "mechanical_seal_failure",
            "root_causes": ["dry_running_seal_face"],
            "must_cite_evidence": [{"signal_role": "vibration_radial"}],
        },
    }
    base.update(overrides)
    return base


def test_scenario_parses_with_trajectories_and_events():
    sc = Scenario.model_validate(_scenario_dict())
    assert sc.affected_asset == "P-101A"
    assert sc.failure_mode_iso14224 == "LEK"
    assert sc.t0 == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert sc.signal_trajectories[1].steps[0].at_day == 18
    assert sc.events[0].sink == "maximo"


def test_scenario_t0_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        Scenario.model_validate(_scenario_dict(t0="2026-03-01T00:00:00"))


def test_time_axis_parses_clock_skews():
    ta = TimeAxis.model_validate(
        {
            "version": 1,
            "reference_time": "2026-03-01T00:00:00Z",
            "clock_skews": {"pi": 0.0, "maximo": 1.5, "sap_pm": -2.3},
        }
    )
    assert ta.reference_time == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert ta.clock_skews["maximo"] == 1.5
