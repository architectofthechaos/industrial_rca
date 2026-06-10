"""S2.4 — SAP PM OData v2 HTTP simulator tests (FastAPI TestClient, no network).

Covers $metadata, the NotificationSet entity set with $filter/$select, and the
full CSRF token dance (Fetch handshake required before writes).
"""
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.sap_pm.app import create_app

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
BASE = "/sap/opu/odata/sap/PM_NOTIFICATION_SRV"
NOTIFS = f"{BASE}/NotificationSet"


def client():
    return TestClient(create_app(load(REFPLANT)))


def fetch_token(c):
    r = c.get(NOTIFS, headers={"X-CSRF-Token": "Fetch"})
    return r.headers["x-csrf-token"]


def test_metadata_returns_edmx():
    r = client().get(f"{BASE}/$metadata")
    assert r.status_code == 200
    assert "Edmx" in r.text and "NotificationSet" in r.text


def test_notificationset_uses_odata_v2_envelope():
    r = client().get(NOTIFS)
    body = r.json()
    assert "d" in body and "results" in body["d"]
    assert any("QMNUM" in n for n in body["d"]["results"])


def test_filter_by_equipment_number():
    r = client().get(NOTIFS, params={"$filter": "EQUNR eq '10001234'"})
    results = r.json()["d"]["results"]
    assert results
    assert {n["EQUNR"] for n in results} == {"10001234"}   # P-101A only


def test_select_projects_fields():
    r = client().get(NOTIFS, params={"$select": "QMNUM,EQUNR"})
    assert all(set(n) <= {"QMNUM", "EQUNR"} for n in r.json()["d"]["results"])


def test_csrf_fetch_returns_token():
    token = fetch_token(client())
    assert token and token not in {"Fetch", "Required"}


def test_write_without_csrf_token_is_rejected():
    c = client()
    r = c.post(NOTIFS, json={"QMNUM": "90000001", "EQUNR": "10001234", "QMTXT": "new"})
    assert r.status_code == 403


def test_fetch_then_write_succeeds_and_is_idempotent():
    c = client()
    token = fetch_token(c)
    before = len(c.get(NOTIFS).json()["d"]["results"])
    payload = {"QMNUM": "90000001", "EQUNR": "10001234", "QMTXT": "new notification"}
    r1 = c.post(NOTIFS, json=payload, headers={"X-CSRF-Token": token})
    assert r1.status_code in (200, 201)
    after_first = len(c.get(NOTIFS).json()["d"]["results"])
    c.post(NOTIFS, json=payload, headers={"X-CSRF-Token": token})   # replay
    after_second = len(c.get(NOTIFS).json()["d"]["results"])
    assert after_first == before + 1
    assert after_second == after_first                              # no duplicate
