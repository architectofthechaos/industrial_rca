"""S2.2 — PI Web API HTTP simulator tests (FastAPI TestClient, no network).

Serves the four endpoints; modes return mode-correct, materially different
responses; WebIDs resolve; scenarios produce the expected anomaly shape.
"""
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.pi.app import create_app
from rca_simulator.pi.webid import encode_webid

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"


def client_and_rp():
    rp = load(REFPLANT)
    app = create_app(rp, scenario_id=SCENARIO)
    return TestClient(app), rp


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def win(rp, day, hours=1):
    start = rp.scenarios[SCENARIO].t0 + timedelta(days=day)
    return iso(start), iso(start + timedelta(hours=hours))


def test_recorded_endpoint_returns_pi_items():
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    s, e = win(rp, 5)
    r = c.get(f"/streams/{wid}/recorded", params={"startTime": s, "endTime": e})
    assert r.status_code == 200
    items = r.json()["Items"]
    assert items and {"Timestamp", "Value", "Good"} <= set(items[0])


def test_interpolated_is_regular_and_flagged():
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    s, e = win(rp, 5)
    r = c.get(f"/streams/{wid}/interpolated",
              params={"startTime": s, "endTime": e, "interval": "60s"})
    items = r.json()["Items"]
    assert len(items) == 60
    assert all(it["IsInterpolated"] for it in items)


def test_summary_returns_typed_aggregates():
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    s, e = win(rp, 5)
    r = c.get(f"/streams/{wid}/summary",
              params={"startTime": s, "endTime": e,
                      "summaryType": "Average", "summaryDuration": "15m"})
    items = r.json()["Items"]
    assert len(items) == 4
    assert items[0]["Type"] == "Average"
    assert "Value" in items[0]["Value"]      # PI nests the aggregate value object


def test_three_modes_materially_different():
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")
    s, e = win(rp, 5)
    rec = c.get(f"/streams/{wid}/recorded", params={"startTime": s, "endTime": e})
    interp = c.get(f"/streams/{wid}/interpolated",
                   params={"startTime": s, "endTime": e, "interval": "60s"})
    summ = c.get(f"/streams/{wid}/summary",
                 params={"startTime": s, "endTime": e,
                         "summaryType": "Average", "summaryDuration": "15m"})
    sizes = {len(rec.json()["Items"]), len(interp.json()["Items"]), len(summ.json()["Items"])}
    assert len(sizes) == 3


def test_scenario_anomaly_shape_seal_leak_pressure_drops():
    c, rp = client_and_rp()
    wid = encode_webid("P-101A.discharge_pressure")

    def avg(day):
        s, e = win(rp, day)
        r = c.get(f"/streams/{wid}/summary",
                  params={"startTime": s, "endTime": e,
                          "summaryType": "Average", "summaryDuration": "60m"})
        return r.json()["Items"][0]["Value"]["Value"]

    assert avg(29) < avg(1) - 100            # seal leak decays discharge pressure


def test_unknown_webid_returns_404():
    c, rp = client_and_rp()
    s, e = win(rp, 5)
    r = c.get("/streams/S1bogus/recorded", params={"startTime": s, "endTime": e})
    assert r.status_code == 404


def test_eventframes_returns_scenario_alarm():
    c, rp = client_and_rp()
    s = iso(rp.scenarios[SCENARIO].t0)
    e = iso(rp.scenarios[SCENARIO].t0 + timedelta(days=30))
    r = c.get("/eventframes", params={"startTime": s, "endTime": e})
    assert r.status_code == 200
    names = " ".join(it["Name"] for it in r.json()["Items"])
    assert "ALM-2026-03-13-9912" in names
