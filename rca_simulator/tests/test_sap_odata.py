"""S2.4 — SAP OData v2 parsing + notification seeding (pure, no HTTP).

SAP models the same assets as Maximo but with different field names/codes
(QMNUM/EQUNR/QMTXT…) to exercise the connector's normalization + dedup path.
"""
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.sap_pm.odata import (
    apply_filter,
    apply_select,
    metadata_xml,
    odata_collection,
    parse_filter,
)
from rca_simulator.sap_pm.seed import SAP_ASSETS, seed_notifications

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"


def rp():
    return load(REFPLANT)


# ---------- $filter ----------

def test_parse_filter_eq():
    assert parse_filter("EQUNR eq '10001234'") == [("EQUNR", "eq", "10001234")]


def test_parse_filter_and():
    conds = parse_filter("EQUNR eq '10001234' and PRIOK eq '1'")
    assert ("EQUNR", "eq", "10001234") in conds
    assert ("PRIOK", "eq", "1") in conds


def test_apply_filter():
    recs = [{"EQUNR": "10001234"}, {"EQUNR": "10001255"}]
    assert apply_filter(recs, parse_filter("EQUNR eq '10001234'")) == [{"EQUNR": "10001234"}]


def test_apply_select():
    recs = [{"QMNUM": "1", "QMTXT": "x", "EQUNR": "9"}]
    assert apply_select(recs, "QMNUM,QMTXT") == [{"QMNUM": "1", "QMTXT": "x"}]


# ---------- OData v2 envelope + metadata ----------

def test_collection_uses_odata_v2_envelope():
    env = odata_collection([{"QMNUM": "1"}])
    assert env == {"d": {"results": [{"QMNUM": "1"}]}}


def test_metadata_is_edmx_with_namespace_and_entity():
    xml = metadata_xml()
    assert "Edmx" in xml
    assert "Namespace" in xml
    assert "Notification" in xml


# ---------- seeding ----------

def test_sap_models_a_subset_overlapping_maximo():
    assert "P-101A" in SAP_ASSETS          # shared with Maximo (overlap)
    assert "P-101B" not in SAP_ASSETS      # not every asset is on SAP


def test_notifications_use_sap_field_names_and_equipment_number():
    notes = seed_notifications(rp())
    # the seal-leak event appears under SAP's schema, keyed by EQUNR (not location)
    seal = [n for n in notes if n["EQUNR"] == "10001234"]   # P-101A sap_equipment
    assert seal
    assert {"QMNUM", "QMTXT", "QMART"} <= set(seal[0])       # SAP field names
    assert "location" not in seal[0] and "wonum" not in seal[0]
