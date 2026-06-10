"""Sprint 1 WI3 — PI AF asset-hierarchy endpoint tests (FastAPI TestClient).

List databases, walk Site -> Area -> Unit -> Asset, read attributes; verify
nameFilter / searchFullHierarchy / maxCount semantics and the acceptance
criteria from sprint1_spec.md section 3.5.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.fixtures.loader import load
from rca_simulator.pi.app import create_app

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"


def client_and_rp():
    rp = load(REFPLANT)
    return TestClient(create_app(rp, scenario_id=SCENARIO)), rp


def db_webid(c):
    return c.get("/assetdatabases").json()["Items"][0]["WebId"]


def children(c, web_id, **params):
    r = c.get(f"/elements/{web_id}/elements", params=params)
    assert r.status_code == 200
    return r.json()["Items"]


def site_element(c):
    """Return the single site root element from the default database."""
    return c.get(f"/assetdatabases/{db_webid(c)}/elements").json()["Items"][0]


def test_assetdatabases_lists_refinery_gc():
    c, _ = client_and_rp()
    r = c.get("/assetdatabases")
    assert r.status_code == 200
    items = r.json()["Items"]
    assert len(items) == 1
    db = items[0]
    assert db["Name"] == "Refinery-GC"
    assert {"WebId", "Name", "Description", "Path"} <= set(db)
    assert db["Path"] == r"\\PI-DEMO\Refinery-GC"


def test_assetdatabase_by_webid():
    c, _ = client_and_rp()
    wid = db_webid(c)
    r = c.get(f"/assetdatabases/{wid}")
    assert r.status_code == 200
    assert r.json()["Name"] == "Refinery-GC"


def test_database_root_elements_is_the_site():
    c, _ = client_and_rp()
    r = c.get(f"/assetdatabases/{db_webid(c)}/elements")
    assert r.status_code == 200
    items = r.json()["Items"]
    assert [el["Name"] for el in items] == ["SITE-DEMO"]
    site = items[0]
    assert site["TemplateName"] == "Site"
    assert site["HasChildren"] is True
    assert site["Path"] == r"\\PI-DEMO\Refinery-GC\SITE-DEMO"


def test_drill_down_site_area_unit_asset():
    c, _ = client_and_rp()
    site = site_element(c)

    areas = children(c, site["WebId"])
    assert {a["Name"] for a in areas} == {"AREA-100", "AREA-200"}

    area_100 = next(a for a in areas if a["Name"] == "AREA-100")
    units = children(c, area_100["WebId"])
    assert {u["Name"] for u in units} == {"UNIT-101", "UNIT-102"}

    unit_101 = next(u for u in units if u["Name"] == "UNIT-101")
    pumps = children(c, unit_101["WebId"])
    assert {p["Name"] for p in pumps} == {"P-101A", "P-101B"}
    assert all(p["HasChildren"] is False for p in pumps)


def test_known_pump_reachable_via_namefilter_drilldown():
    c, _ = client_and_rp()
    site = site_element(c)
    areas = children(c, site["WebId"], nameFilter="AREA-1*")
    assert [a["Name"] for a in areas] == ["AREA-100"]
    units = children(c, areas[0]["WebId"], nameFilter="UNIT-101")
    assert [u["Name"] for u in units] == ["UNIT-101"]
    pumps = children(c, units[0]["WebId"], nameFilter="p-101a")  # case-insensitive
    assert [p["Name"] for p in pumps] == ["P-101A"]


def test_element_by_webid_has_af_shape():
    c, _ = client_and_rp()
    site = site_element(c)
    pump = children(c, site["WebId"], searchFullHierarchy=True,
                    nameFilter="P-101A")[0]
    r = c.get(f"/elements/{pump['WebId']}")
    assert r.status_code == 200
    el = r.json()
    assert {"WebId", "Name", "Description", "Path", "TemplateName",
            "CategoryNames", "HasChildren"} <= set(el)
    assert el["Name"] == "P-101A"
    assert el["Path"] == r"\\PI-DEMO\Refinery-GC\SITE-DEMO\AREA-100\UNIT-101\P-101A"
    assert el["TemplateName"] == "centrifugal_pump"
    assert el["CategoryNames"] == ["Asset"]
    assert el["HasChildren"] is False


def test_full_hierarchy_from_site_returns_every_fixture_asset():
    """Acceptance 3.5: full-hierarchy traversal reaches every asset in the fixture."""
    c, rp = client_and_rp()
    site = site_element(c)
    everything = children(c, site["WebId"], searchFullHierarchy=True)
    names = {el["Name"] for el in everything}
    assert set(rp.assets) <= names                      # all 4 assets present
    assert {"AREA-100", "AREA-200", "UNIT-101",
            "UNIT-102", "UNIT-201"} <= names            # plus intermediate levels
    assert "SITE-DEMO" not in names                     # strict descendants only


def test_full_hierarchy_from_database_includes_root():
    c, rp = client_and_rp()
    r = c.get(f"/assetdatabases/{db_webid(c)}/elements",
              params={"searchFullHierarchy": "true"})
    names = {el["Name"] for el in r.json()["Items"]}
    assert "SITE-DEMO" in names
    assert set(rp.assets) <= names


def test_maxcount_truncates_after_filtering():
    c, _ = client_and_rp()
    site = site_element(c)
    pumps = children(c, site["WebId"], searchFullHierarchy=True,
                     nameFilter="P-10*", maxCount=2)
    assert len(pumps) == 2
    assert all(p["Name"].startswith("P-10") for p in pumps)


def test_asset_attributes_flat_name_value_list():
    c, rp = client_and_rp()
    site = site_element(c)
    pump = children(c, site["WebId"], searchFullHierarchy=True,
                    nameFilter="P-101A")[0]
    r = c.get(f"/elements/{pump['WebId']}/attributes")
    assert r.status_code == 200
    items = r.json()["Items"]
    assert all({"WebId", "Name", "Value"} <= set(it) for it in items)
    by_name = {it["Name"]: it["Value"] for it in items}
    asset = rp.assets["P-101A"]
    assert by_name["Manufacturer"] == asset.nameplate.manufacturer
    assert by_name["Model"] == asset.nameplate.model
    assert by_name["SerialNumber"] == asset.nameplate.serial
    assert by_name["Criticality"] == asset.criticality
    assert by_name["ISO14224Class"] == asset.iso14224_class
    assert by_name["ServiceDescription"] == asset.service


def test_unknown_element_webid_returns_404():
    c, _ = client_and_rp()
    assert c.get("/elements/S1bogus").status_code == 404
    assert c.get("/elements/S1bogus/elements").status_code == 404
    assert c.get("/elements/S1bogus/attributes").status_code == 404
    assert c.get("/assetdatabases/S1bogus").status_code == 404
    assert c.get("/assetdatabases/S1bogus/elements").status_code == 404


def test_stream_endpoints_unbroken_by_af_routes():
    """The four pre-existing stream/eventframe routes still resolve (regression guard)."""
    c, _ = client_and_rp()
    paths = {route.path for route in c.app.routes}
    assert {"/streams/{web_id}/recorded", "/streams/{web_id}/interpolated",
            "/streams/{web_id}/summary", "/eventframes"} <= paths
    assert c.get("/openapi.json").status_code == 200    # /docs schema intact


# ---- Edge-case tests (Sprint-1 deviations and empty-result paths) -----------

def test_maxcount_zero_returns_empty():
    """maxCount=0 → empty Items (PI Web API semantics; real PI also returns 0 items)."""
    c, _ = client_and_rp()
    site = site_element(c)
    assert children(c, site["WebId"], maxCount=0) == []


def test_negative_maxcount_returns_empty():
    """Negative maxCount is clamped to empty rather than HTTP 400.
    Real PI Web API returns HTTP 400 for maxCount < 0 — accepted Sprint-1 deviation."""
    c, _ = client_and_rp()
    site = site_element(c)
    assert children(c, site["WebId"], maxCount=-1) == []


def test_unit_element_attributes_returns_empty():
    """Non-asset elements (Site/Area/Unit) carry no attributes → empty Items."""
    c, _ = client_and_rp()
    site = site_element(c)
    unit_101 = next(
        u for a in children(c, site["WebId"])
        if a["Name"] == "AREA-100"
        for u in children(c, a["WebId"])
        if u["Name"] == "UNIT-101"
    )
    r = c.get(f"/elements/{unit_101['WebId']}/attributes")
    assert r.status_code == 200
    assert r.json()["Items"] == []


def test_no_match_namefilter_returns_empty():
    """nameFilter with no match → empty Items (not a 404)."""
    c, _ = client_and_rp()
    site = site_element(c)
    assert children(c, site["WebId"], nameFilter="NO-SUCH-ELEMENT-*") == []
