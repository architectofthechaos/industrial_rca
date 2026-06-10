"""S2.2 — PI WebID + synthesis mode-semantics tests (pure, no HTTP).

The three PI modes must behave differently and mode-correctly for the same
signal and range: stored (compression), interpolated (regular grid, flagged),
aggregated (true aggregates per interval).
"""
from datetime import timedelta
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.pi.webid import decode_webid, encode_webid
from rca_simulator.pi.synthesize import aggregated, interpolated, recorded

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"
KEY = "P-101A.discharge_pressure"


def rp():
    return load(REFPLANT)


def window(p, hours=1):
    start = p.scenarios[SCENARIO].t0 + timedelta(days=5)
    return start, start + timedelta(hours=hours)


# ---------- WebID ----------

def test_webid_round_trips():
    wid = encode_webid(KEY)
    assert wid != KEY                       # opaque-ish identifier
    assert decode_webid(wid) == KEY


def test_webids_unique_per_signal():
    p = rp()
    ids = {encode_webid(k) for k in p.signals}
    assert len(ids) == len(p.signals)


# ---------- recorded / stored (compression) ----------

def test_recorded_compression_is_monotonic_in_threshold():
    p = rp()
    start, end = window(p)
    none = recorded(p, SCENARIO, KEY, start, end, compression=0.0)
    some = recorded(p, SCENARIO, KEY, start, end, compression=50.0)
    assert len(none) > len(some)            # tighter compression keeps fewer points
    assert len(none) == 3600                # comp=0 keeps every 1-second sample


def test_recorded_first_point_always_kept():
    p = rp()
    start, end = window(p)
    pts = recorded(p, SCENARIO, KEY, start, end, compression=1e9)
    assert pts[0].timestamp == start        # huge threshold still keeps the first


# ---------- interpolated (regular grid, flagged) ----------

def test_interpolated_is_regular_grid_and_flagged():
    p = rp()
    start, end = window(p)
    pts = interpolated(p, SCENARIO, KEY, start, end, interval_seconds=60)
    assert len(pts) == 60                    # 1-minute grid over 1 hour
    assert all(pt.is_interpolated for pt in pts)
    gaps = {(pts[i + 1].timestamp - pts[i].timestamp).total_seconds()
            for i in range(len(pts) - 1)}
    assert gaps == {60.0}                     # evenly spaced


def test_modes_return_materially_different_responses():
    p = rp()
    start, end = window(p)
    rec = recorded(p, SCENARIO, KEY, start, end, compression=0.0)
    interp = interpolated(p, SCENARIO, KEY, start, end, interval_seconds=60)
    agg = aggregated(p, SCENARIO, KEY, start, end, duration_seconds=900, summary_type="Average")
    assert len({len(rec), len(interp), len(agg)}) == 3   # all different sizes


# ---------- aggregated (true aggregates per interval) ----------

def test_aggregated_average_per_interval():
    p = rp()
    start, end = window(p)
    agg = aggregated(p, SCENARIO, KEY, start, end, duration_seconds=900, summary_type="Average")
    assert len(agg) == 4                      # four 15-minute buckets in an hour
    base = p.signals[KEY].baseline.mean
    for _ts, value in agg:
        assert abs(value - base) < 200        # averages sit near baseline (+ early decay)
