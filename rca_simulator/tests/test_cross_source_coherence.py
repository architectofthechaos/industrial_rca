"""Cross-source coherence (SPEC-014 test plan #3).

The single most valuable integration test: for one scenario, the PI time series,
the Maximo work orders, and the SAP notifications must all describe the same
event on the same timeline (t0 + offset). This is what makes the fixture the
shared source of truth across simulators.
"""
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.maximo.app import create_app as maximo_app
from rca_simulator.pi.app import create_app as pi_app
from rca_simulator.pi.webid import encode_webid
from rca_simulator.sap_pm.app import create_app as sap_app

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_seal_leak_aligns_across_pi_maximo_sap():
    rp = load(REFPLANT)
    t0 = rp.scenarios[SCENARIO].t0
    tz = rp.plant.site.timezone

    pi = TestClient(pi_app(rp, scenario_id=SCENARIO))
    mx = TestClient(maximo_app(rp))
    sap = TestClient(sap_app(rp))

    # 1) PI: discharge pressure has decayed by the time the leak WO is raised (day 28)
    wid = encode_webid("P-101A.discharge_pressure")

    def pi_avg(day):
        s = t0 + timedelta(days=day)
        r = pi.get(f"/streams/{wid}/summary",
                   params={"startTime": _iso(s), "endTime": _iso(s + timedelta(hours=1)),
                           "summaryType": "Average", "summaryDuration": "60m"})
        return r.json()["Items"][0]["Value"]["Value"]

    assert pi_avg(28) < pi_avg(1) - 100

    # 2) Maximo: the leak WO exists for P-101A, dated t0 + 28 days (site-local)
    wo = next(m for m in mx.get("/maxrest/oslc/os/mxwo").json()["member"]
              if m["wonum"] == "WO-50012402")
    assert wo["location"] == "CRDU-P101A"
    expected_local = (t0 + timedelta(days=28)).astimezone(ZoneInfo(tz)).replace(tzinfo=None)
    assert wo["reportdate"] == expected_local.strftime("%Y-%m-%dT%H:%M:%S")

    # 3) SAP: the SAME event appears under SAP's schema for P-101A's equipment number,
    #    dated the same day (yyyymmdd) — different field names, one underlying reality.
    note = next(n for n in sap.get(
        "/sap/opu/odata/sap/PM_NOTIFICATION_SRV/NotificationSet").json()["d"]["results"]
        if n["EQUNR"] == "10001234" and n["FECOD"] == "0010")   # P-101A, LEAK->0010
    assert note["AUSVN"] == (t0 + timedelta(days=28)).strftime("%Y%m%d")


def test_pi_af_view_matches_maximo_and_historian_for_pump():
    """Sprint 1 WI3: the PI AF element for P-101A, the Maximo location/EQUNR ids,
    and the PI Historian streams all describe the same fixture asset — vendor IDs
    differ, identity (the fixture asset tag) is one."""
    rp = load(REFPLANT)
    asset = rp.assets["P-101A"]
    pi = TestClient(pi_app(rp, scenario_id=SCENARIO))
    mx = TestClient(maximo_app(rp))

    # 1) PI AF: drill the hierarchy down to the pump element.
    db = pi.get("/assetdatabases").json()["Items"][0]
    pump = pi.get(f"/assetdatabases/{db['WebId']}/elements",
                  params={"searchFullHierarchy": "true",
                          "nameFilter": asset.tag}).json()["Items"][0]
    assert pump["Name"] == asset.tag
    assert pump["Path"].endswith("\\" + asset.tag)
    # AF attributes mirror the asset fixture row.
    attrs = {a["Name"]: a["Value"] for a in
             pi.get(f"/elements/{pump['WebId']}/attributes").json()["Items"]}
    assert attrs["Manufacturer"] == asset.nameplate.manufacturer
    assert attrs["SerialNumber"] == asset.nameplate.serial

    # 2) Maximo: the seal-leak WO for this same asset uses its maximo_location
    #    external id (CRDU-P101A) — different vendor id, same fixture identity.
    wo = next(m for m in mx.get("/maxrest/oslc/os/mxwo").json()["member"]
              if m["wonum"] == "WO-50012402")
    assert wo["location"] == asset.external_ids["maximo_location"]

    # 3) PI Historian: the same asset's stream (keyed "<tag>.<role>") serves data
    #    from the very same app that serves the AF hierarchy.
    wid = encode_webid(f"{asset.tag}.discharge_pressure")
    s = rp.scenarios[SCENARIO].t0 + timedelta(days=5)
    r = pi.get(f"/streams/{wid}/recorded",
               params={"startTime": _iso(s),
                       "endTime": _iso(s + timedelta(hours=1))})
    assert r.status_code == 200 and r.json()["Items"]
