"""S2.1 — scenario expander tests.

The expander turns a scenario into deterministic signal values: a pure
``value_at`` core (simulators sample it on demand), a materializer, and discrete
event extraction keyed by sink. Determinism must hold across calls (and across
processes — so no salted builtin hash in the seed).
"""
import statistics
from datetime import timedelta
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.fixtures.scenario_expander import (
    events_by_sink,
    expand_series,
    value_at,
)

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"


def rp():
    return load(REFPLANT)


def day(plant, scenario_id, n):
    return plant.scenarios[scenario_id].t0 + timedelta(days=n)


# ---------- trajectory shapes (noise off, sampled at whole days → diurnal=0) ----------

def test_linear_decay_interpolates_start_to_end():
    p = rp()
    base = p.signals["P-101A.discharge_pressure"].baseline.mean  # 1450, end_offset -180
    v0 = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                  day(p, "seal_leak_progression", 0), with_noise=False)
    v15 = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                   day(p, "seal_leak_progression", 15), with_noise=False)
    v30 = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                   day(p, "seal_leak_progression", 30), with_noise=False)
    assert v0 == base
    assert v15 == base - 90
    assert v30 == base - 180


def test_linear_growth_rises():
    p = rp()
    base = p.signals["P-101A.motor_amps"].baseline.mean  # end_offset +8
    v30 = value_at(p, "seal_leak_progression", "P-101A.motor_amps",
                   day(p, "seal_leak_progression", 30), with_noise=False)
    assert v30 == base + 8


def test_step_then_growth_is_a_rising_step_function():
    p = rp()
    base = p.signals["P-101A.vibration_radial"].baseline.mean
    before = value_at(p, "seal_leak_progression", "P-101A.vibration_radial",
                      day(p, "seal_leak_progression", 10), with_noise=False)
    after_first = value_at(p, "seal_leak_progression", "P-101A.vibration_radial",
                           day(p, "seal_leak_progression", 20), with_noise=False)
    after_second = value_at(p, "seal_leak_progression", "P-101A.vibration_radial",
                            day(p, "seal_leak_progression", 27), with_noise=False)
    assert before == base
    assert after_first == base + 1.2
    assert after_second == base + 4.5


def test_offset_clamped_outside_scenario_window():
    p = rp()
    base = p.signals["P-101A.discharge_pressure"].baseline.mean
    before = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                      day(p, "seal_leak_progression", -5), with_noise=False)
    after = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                     day(p, "seal_leak_progression", 60), with_noise=False)
    assert before == base                 # before t0: baseline
    assert after == base - 180            # after end: holds final offset


# ---------- scenario isolation ----------

def test_unaffected_asset_sees_baseline_only():
    p = rp()
    base = p.signals["P-101B.discharge_pressure"].baseline.mean
    v0 = value_at(p, "seal_leak_progression", "P-101B.discharge_pressure",
                  day(p, "seal_leak_progression", 0), with_noise=False)
    v30 = value_at(p, "seal_leak_progression", "P-101B.discharge_pressure",
                   day(p, "seal_leak_progression", 30), with_noise=False)
    assert v0 == base and v30 == base     # P-101B untouched by a P-101A scenario


# ---------- determinism & noise ----------

def test_value_at_is_deterministic_with_noise():
    p = rp()
    t = day(p, "seal_leak_progression", 7) + timedelta(seconds=12345)
    a = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure", t)
    b = value_at(p, "seal_leak_progression", "P-101A.discharge_pressure", t)
    assert a == b


def test_noise_actually_varies_the_signal():
    p = rp()
    t0 = day(p, "seal_leak_progression", 2)
    vals = [value_at(p, "seal_leak_progression", "P-101A.discharge_pressure",
                     t0 + timedelta(seconds=s)) for s in range(200)]
    assert statistics.pstdev(vals) > 0.0


def test_expand_series_is_deterministic_and_well_formed():
    p = rp()
    start = day(p, "seal_leak_progression", 0)
    end = start + timedelta(minutes=5)
    s1 = expand_series(p, "seal_leak_progression", "P-101A.discharge_pressure",
                       start, end, step_seconds=60)
    s2 = expand_series(p, "seal_leak_progression", "P-101A.discharge_pressure",
                       start, end, step_seconds=60)
    assert s1 == s2
    assert len(s1) == 5                    # 5 one-minute samples in [start, end)
    assert all(ts.tzinfo is not None for ts, _ in s1)


# ---------- discrete events ----------

def test_events_grouped_by_sink_with_absolute_timestamps():
    p = rp()
    sinks = events_by_sink(p, "seal_leak_progression")
    assert set(sinks) == {"documents", "alarms", "maximo"}
    assert len(sinks["maximo"]) == 2
    # absolute timestamp = t0 + at_day
    t0 = p.scenarios["seal_leak_progression"].t0
    ts, ev = sinks["maximo"][0]
    assert ev.payload["wo_number"] == "WO-50012345"
    assert ts == t0 + timedelta(days=ev.at_day)
