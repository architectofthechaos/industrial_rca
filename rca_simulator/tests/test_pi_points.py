"""Sprint 2b Track 3 — PI points discovery, stream value, and event-frame fetch tests.

Tests for three new PI Web API surface endpoints:
  GET /points?nameFilter=<glob>&maxCount=<int>
  GET /points/{webId}
  GET /streams/{webId}/value?time=<iso8601>
  GET /eventframes/{id}
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.pi.app import create_app
from rca_simulator.pi.webid import decode_webid, encode_webid

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"

_P101A_ROLES = {
    "discharge_pressure",
    "suction_pressure",
    "motor_amps",
    "bearing_temp_de",
    "vibration_radial",
    "seal_flush_flow",
}
P101A_SIGNALS = {f"P-101A.{role}" for role in _P101A_ROLES}

SEAL_ALARM_ID = "ALM-2026-03-13-9912"


def client_and_rp():
    rp = load(REFPLANT)
    app = create_app(rp, scenario_id=SCENARIO)
    return TestClient(app), rp


# ---------------------------------------------------------------------------
# /points — tag discovery
# ---------------------------------------------------------------------------

def test_points_namefilter_p101a_returns_six_items():
    """nameFilter=P-101A.* matches exactly the 6 P-101A signals."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.*"})
    assert r.status_code == 200
    items = r.json()["Items"]
    assert len(items) == 6
    names = {it["Name"] for it in items}
    assert names == P101A_SIGNALS


def test_points_items_have_required_fields():
    """Every PiPoint item carries WebId, Name, Path, Descriptor, EngineeringUnits."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.*"})
    items = r.json()["Items"]
    for it in items:
        assert {"WebId", "Name", "Path", "Descriptor", "EngineeringUnits"} <= set(it), (
            f"missing fields in {it}"
        )


def test_points_webid_agrees_with_streams_webid():
    """The WebId for P-101A.discharge_pressure in /points equals encode_webid of the key."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.discharge_pressure"})
    items = r.json()["Items"]
    assert len(items) == 1
    pt = items[0]
    expected_webid = encode_webid("P-101A.discharge_pressure")
    assert pt["WebId"] == expected_webid, (
        f"WebId mismatch: points returned {pt['WebId']!r}, "
        f"encode_webid gives {expected_webid!r}"
    )


def test_points_webid_can_be_decoded_to_signal_key():
    """Every WebId in /points decodes back to the same Name via decode_webid."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.*"})
    for it in r.json()["Items"]:
        assert decode_webid(it["WebId"]) == it["Name"]


def test_points_default_no_filter_returns_all_signals():
    """Without nameFilter, all signals are returned (up to maxCount)."""
    c, rp = client_and_rp()
    r = c.get("/points")
    assert r.status_code == 200
    items = r.json()["Items"]
    assert len(items) == len(rp.signals)


def test_points_maxcount_truncates():
    """maxCount truncates the filtered result as PI Web API does."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.*", "maxCount": 3})
    assert r.status_code == 200
    assert len(r.json()["Items"]) == 3


def test_points_namefilter_case_insensitive():
    """nameFilter is case-insensitive."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "p-101a.*"})
    assert r.status_code == 200
    assert len(r.json()["Items"]) == 6


def test_points_descriptor_and_units_populated():
    """Descriptor matches display_name; EngineeringUnits matches first source units_raw."""
    c, rp = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.discharge_pressure"})
    item = r.json()["Items"][0]
    sig = rp.signals["P-101A.discharge_pressure"]
    assert item["Descriptor"] == sig.display_name
    assert item["EngineeringUnits"] == sig.source_systems[0].units_raw


def test_points_path_contains_name():
    """Path is a non-empty string and contains the signal Name."""
    c, _ = client_and_rp()
    r = c.get("/points", params={"nameFilter": "P-101A.discharge_pressure"})
    item = r.json()["Items"][0]
    assert item["Path"] and item["Name"] in item["Path"]


# ---------------------------------------------------------------------------
# /points/{webId} — single point lookup
# ---------------------------------------------------------------------------

def test_points_by_webid_round_trips():
    """GET /points/{webId} returns the bare PiPoint for a valid signal."""
    c, _ = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    r = c.get(f"/points/{wid}")
    assert r.status_code == 200
    pt = r.json()
    assert pt["Name"] == "P-101A.discharge_pressure"
    assert pt["WebId"] == wid
    assert {"WebId", "Name", "Path", "Descriptor", "EngineeringUnits"} <= set(pt)


def test_points_by_webid_unknown_returns_404():
    """Unknown WebId → 404."""
    c, _ = client_and_rp()
    r = c.get("/points/S1bogus")
    assert r.status_code == 404


def test_points_by_webid_not_wrapped_in_items():
    """Single-point GET returns a bare object, not {"Items": [...]}."""
    c, _ = client_and_rp()
    wid = encode_webid("P-101A.vibration_radial")
    body = c.get(f"/points/{wid}").json()
    assert "Items" not in body


# ---------------------------------------------------------------------------
# /streams/{webId}/value — single value at time
# ---------------------------------------------------------------------------

def test_stream_value_returns_value_object():
    """GET /streams/{webId}/value → {Timestamp, Value, Good}."""
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    t = (rp.time_axis.window_end or rp.time_axis.reference_time).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = c.get(f"/streams/{wid}/value", params={"time": t})
    assert r.status_code == 200
    body = r.json()
    assert {"Timestamp", "Value", "Good"} <= set(body)
    assert isinstance(body["Value"], float)
    assert body["Good"] is True


def test_stream_value_deterministic_for_same_time():
    """Two calls with the same time= param return the same Value."""
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    t = "2026-03-15T12:00:00Z"
    r1 = c.get(f"/streams/{wid}/value", params={"time": t})
    r2 = c.get(f"/streams/{wid}/value", params={"time": t})
    assert r1.json()["Value"] == r2.json()["Value"]


def test_stream_value_default_time_is_window_end():
    """Without time= param, uses fixture window_end (response should be 200)."""
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    r = c.get(f"/streams/{wid}/value")
    assert r.status_code == 200
    body = r.json()
    assert "Value" in body


def test_stream_value_unknown_webid_returns_404():
    """Unknown WebId → 404."""
    c, _ = client_and_rp()
    r = c.get("/streams/S1bogus/value")
    assert r.status_code == 404


def test_stream_value_changes_over_scenario_time():
    """Values at day 1 and day 29 differ under seal_leak_progression for discharge_pressure."""
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    t0 = rp.scenarios[SCENARIO].t0
    from datetime import timedelta
    t1 = (t0 + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t29 = (t0 + timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
    v1 = c.get(f"/streams/{wid}/value", params={"time": t1}).json()["Value"]
    v29 = c.get(f"/streams/{wid}/value", params={"time": t29}).json()["Value"]
    # pressure decays under seal_leak_progression
    assert v29 < v1


# ---------------------------------------------------------------------------
# /eventframes/{id} — single event frame by Name
# ---------------------------------------------------------------------------

def test_eventframes_by_id_returns_frame():
    """GET /eventframes/{alarm_id} returns the matching frame."""
    c, _ = client_and_rp()
    r = c.get(f"/eventframes/{SEAL_ALARM_ID}")
    assert r.status_code == 200
    frame = r.json()
    assert frame["Name"] == SEAL_ALARM_ID
    assert {"Name", "StartTime", "EndTime", "Template", "Signal"} <= set(frame)


def test_eventframes_by_id_not_wrapped_in_items():
    """Single frame GET returns a bare object, not {"Items": [...]}."""
    c, _ = client_and_rp()
    body = c.get(f"/eventframes/{SEAL_ALARM_ID}").json()
    assert "Items" not in body


def test_eventframes_by_id_times_are_strings():
    """StartTime and EndTime are ISO strings."""
    c, _ = client_and_rp()
    frame = c.get(f"/eventframes/{SEAL_ALARM_ID}").json()
    assert isinstance(frame["StartTime"], str)
    assert isinstance(frame["EndTime"], str)


def test_eventframes_by_id_unknown_returns_404():
    """Unknown alarm id → 404."""
    c, _ = client_and_rp()
    r = c.get("/eventframes/ALM-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_eventframes_list_and_by_id_shape_match():
    """The shape returned by /eventframes/{id} matches items in /eventframes list."""
    c, rp = client_and_rp()
    from datetime import timedelta
    sc = rp.scenarios[SCENARIO]
    s = sc.t0.strftime("%Y-%m-%dT%H:%M:%SZ")
    e = (sc.t0 + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    list_r = c.get("/eventframes", params={"startTime": s, "endTime": e})
    list_items = {it["Name"]: it for it in list_r.json()["Items"]}

    single = c.get(f"/eventframes/{SEAL_ALARM_ID}").json()
    assert SEAL_ALARM_ID in list_items
    # Same fields present in both shapes
    assert set(single.keys()) == set(list_items[SEAL_ALARM_ID].keys())
    # Same values
    assert single == list_items[SEAL_ALARM_ID]
