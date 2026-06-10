"""Sprint 1 WI3 — AF WebID determinism across simulator restarts.

Hierarchy WebIDs encode the element's AF path with the same deterministic
scheme used for streams (pi/webid.py); the same path must produce the same
WebID in two separately-constructed app instances.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.pi.app import create_app
from rca_simulator.pi.webid import decode_webid, encode_webid

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"

PUMP_PATH = r"\\PI-DEMO\Refinery-GC\SITE-DEMO\AREA-100\UNIT-101\P-101A"


def fresh_client():
    """A separately-constructed simulator instance (fresh load, fresh app)."""
    return TestClient(create_app(load(REFPLANT), scenario_id=SCENARIO))


def walk_webids(c):
    """Map AF path -> WebID for the database and every element in it."""
    db = c.get("/assetdatabases").json()["Items"][0]
    out = {db["Path"]: db["WebId"]}
    items = c.get(f"/assetdatabases/{db['WebId']}/elements",
                  params={"searchFullHierarchy": "true"}).json()["Items"]
    out.update({el["Path"]: el["WebId"] for el in items})
    return out


def test_same_path_same_webid_across_restarts():
    first, second = walk_webids(fresh_client()), walk_webids(fresh_client())
    assert first == second
    assert PUMP_PATH in first


def test_hierarchy_webids_use_the_stream_encoding_scheme():
    c = fresh_client()
    db = c.get("/assetdatabases").json()["Items"][0]
    pump = c.get(f"/assetdatabases/{db['WebId']}/elements",
                 params={"searchFullHierarchy": "true",
                         "nameFilter": "P-101A"}).json()["Items"][0]
    assert pump["WebId"] == encode_webid(PUMP_PATH)
    assert decode_webid(pump["WebId"]) == PUMP_PATH


def test_element_webid_resolves_back_to_same_element():
    a, b = fresh_client(), fresh_client()
    wid = encode_webid(PUMP_PATH)
    ra, rb = a.get(f"/elements/{wid}"), b.get(f"/elements/{wid}")
    assert ra.status_code == rb.status_code == 200
    assert ra.json() == rb.json()
    assert ra.json()["Name"] == "P-101A"


def test_element_webids_disjoint_from_stream_webids():
    """Stream WebIDs (tag.role) and element WebIDs (\\\\path) share the codec
    but cannot collide because their encoded payloads are in distinct namespaces."""
    rp = load(REFPLANT)
    stream_webids = {encode_webid(key) for key in rp.signals}

    c = fresh_client()
    db = c.get("/assetdatabases").json()["Items"][0]
    element_webids = {db["WebId"]}
    items = c.get(f"/assetdatabases/{db['WebId']}/elements",
                  params={"searchFullHierarchy": "true"}).json()["Items"]
    element_webids.update(el["WebId"] for el in items)

    assert stream_webids.isdisjoint(element_webids), (
        "Stream and element WebIDs must not overlap; codec namespace collision detected"
    )
