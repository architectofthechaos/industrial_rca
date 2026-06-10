"""S2.3 — Maximo OSLC HTTP simulator tests (FastAPI TestClient, no network)."""
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.maximo.app import create_app
from rca_simulator.realism.config import RealismConfig
from rca_simulator.realism.inject import RealismInjector

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
MXWO = "/maxrest/oslc/os/mxwo"


def client(realism=None):
    return TestClient(create_app(load(REFPLANT), realism=realism))


def test_mxwo_returns_member_list():
    r = client().get(MXWO)
    assert r.status_code == 200
    body = r.json()
    wonums = {m["wonum"] for m in body["member"]}
    assert {"WO-50012345", "WO-50012402"} <= wonums
    assert body["responseInfo"]["totalCount"] >= len(body["member"])


def test_mxwo_where_filters_by_location():
    r = client().get(MXWO, params={"oslc.where": 'location="CRDU-P101A"'})
    members = r.json()["member"]
    assert members
    assert {m["location"] for m in members} == {"CRDU-P101A"}
    assert {"WO-50012345", "WO-50012402"} <= {m["wonum"] for m in members}


def test_mxwo_select_projects_fields():
    r = client().get(MXWO, params={"oslc.select": "wonum,status"})
    assert all(set(m) <= {"wonum", "status"} for m in r.json()["member"])


def test_mxwo_paging():
    r = client().get(MXWO, params={"oslc.pageSize": 2, "oslc.pageNo": 1})
    body = r.json()
    assert len(body["member"]) == 2
    assert body["responseInfo"]["totalCount"] > 2


def test_failrep_has_legacy_code():
    iso = {"LEK", "VIB", "ELP", "STP", "ELE", "ERO"}
    codes = {m["failurecode"] for m in client().get("/maxrest/oslc/os/mxfailrep").json()["member"]}
    assert codes - iso          # at least one non-ISO legacy code


def test_mxsr_returns_service_requests():
    r = client().get("/maxrest/oslc/os/mxsr")
    assert r.status_code == 200
    assert any(m["ticketid"].startswith("SR-") for m in r.json()["member"])


def test_writeback_is_idempotent():
    c = client()
    before = c.get(MXWO).json()["responseInfo"]["totalCount"]
    payload = {"wonum": "WO-99999001", "location": "CRDU-P101A",
               "description": "new corrective", "status": "WAPPR"}
    c.post(MXWO, json=payload)
    after_first = c.get(MXWO).json()["responseInfo"]["totalCount"]
    c.post(MXWO, json=payload)                      # replay
    after_second = c.get(MXWO).json()["responseInfo"]["totalCount"]
    assert after_first == before + 1
    assert after_second == after_first              # no duplicate
    wonums = {m["wonum"] for m in c.get(MXWO).json()["member"]}
    assert "WO-99999001" in wonums


def test_realism_5xx_rate_one_returns_500():
    c = client(realism=RealismInjector(RealismConfig(error_5xx_rate=1.0), seed=1))
    assert c.get(MXWO).status_code == 500
