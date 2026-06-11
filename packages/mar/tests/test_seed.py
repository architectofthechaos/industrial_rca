import re
from pathlib import Path
from uuid import UUID

import pytest

from rca_mar.repository import InMemoryRepository
from rca_mar.seed import seed_from_register

REGISTER = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
P101A = UUID("0190d3c9-0000-7000-8000-000000000001")
P103A = UUID("0190d3c9-0000-7000-8000-000000000004")

CANONICAL_ID_RE = re.compile(r"^asset:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$")

# pi_af aliases are keyed by AF WebId (stable across path renames — Sprint 2a re-key);
# the AF path rides along as vendor_path. Values produced by seed_data/scripts/
# rekey_pi_af_webids.py against the live PI AF simulator.
P101A_WEBID = "S1XFxQSS1ERU1PXFJlZmluZXJ5LUdDXFNJVEUtREVNT1xBUkVBLTEwMFxVTklULTEwMVxQLTEwMUE"
P101A_AF_PATH = r"\\PI-DEMO\Refinery-GC\SITE-DEMO\AREA-100\UNIT-101\P-101A"

# Synth default connection ids the seed mints per legacy source (Sprint 2b §1.2).
CONN_MAXIMO = "refinery-gc.cmms.maximo-default"
CONN_SAP = "refinery-gc.cmms.sap-pm-default"
CONN_PI_AF = "refinery-gc.hierarchy.pi-af-default"
CONN_UNS = "refinery-gc.historian.uns-default"


async def test_seed_populates_assets_and_aliases():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)

    p101a = await repo.get_asset(TENANT, P101A)
    assert p101a is not None and p101a.tag == "P-101A"
    assert p101a.criticality == "A"                 # high -> A mapping
    assert p101a.plant_id == "refinery-gc"

    assert await repo.source_handle_for(TENANT, P101A, CONN_MAXIMO) == "CRDU-P101A"
    assert await repo.source_handle_for(TENANT, P101A, CONN_SAP) == "10001234"
    assert await repo.source_handle_for(TENANT, P101A, CONN_PI_AF) == P101A_WEBID
    assert await repo.source_handle_for(TENANT, P101A, CONN_UNS) == "crude.p101a"

    pi_af = await repo.find_active_alias(TENANT, CONN_PI_AF, P101A_WEBID, valid_at=None)
    assert pi_af is not None and pi_af.vendor_path == P101A_AF_PATH


async def test_seed_registers_leaf_assets_only():
    # units moved to the KG (Sprint 2): the register's `unit:` slug is consumed to mint
    # canonical_id and never lands as an asset row
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    assert {a.iso14224_class for a in repo.assets.values()} == {"pump.centrifugal"}
    assert len(repo.assets) == 2


async def test_seed_mints_canonical_ids_unique_and_well_formed():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)

    p101a = await repo.get_asset(TENANT, P101A)
    p103a = await repo.get_asset(TENANT, P103A)
    assert p101a.canonical_id == "asset:refinery-gc:unit-101:p-101a"
    assert p103a.canonical_id == "asset:refinery-gc:unit-201:p-103a"

    canonical_ids = [a.canonical_id for a in repo.assets.values()]
    assert len(canonical_ids) == len(set(canonical_ids))          # uniqueness
    assert all(CANONICAL_ID_RE.match(c) for c in canonical_ids)   # format


async def test_seed_rejects_unknown_source_system(tmp_path):
    # the register is authoritative input: an unknown external_ids key is a register
    # bug and must fail loudly, never be silently categorized
    register = tmp_path / "register.yaml"
    register.write_text(
        "version: 1\n"
        f"tenant_id: {TENANT}\n"
        "plant_id: refinery-gc\n"
        "assets:\n"
        f"  - asset_id: {P101A}\n"
        "    tag: P-101A\n"
        "    unit: unit-101\n"
        "    iso14224_class: pump.centrifugal\n"
        "    iso14224_level: 6\n"
        "    criticality: high\n"
        "    external_ids:\n"
        "      wonderware: XX-1\n")
    with pytest.raises(ValueError, match="unknown source system 'wonderware'"):
        await seed_from_register(InMemoryRepository(), register)


async def test_seed_rejects_unknown_criticality_word(tmp_path):
    # an unknown criticality word in the register is a register bug; must fail loudly with a
    # helpful message naming the offending value, tag, and the known words
    register = tmp_path / "register.yaml"
    register.write_text(
        "version: 1\n"
        f"tenant_id: {TENANT}\n"
        "plant_id: refinery-gc\n"
        "assets:\n"
        f"  - asset_id: {P101A}\n"
        "    tag: P-101A\n"
        "    unit: unit-101\n"
        "    iso14224_class: pump.centrifugal\n"
        "    iso14224_level: 6\n"
        "    criticality: critical\n")
    with pytest.raises(ValueError, match="unknown criticality 'critical'"):
        await seed_from_register(InMemoryRepository(), register)


async def test_seed_accepts_mapping_external_id_with_vendor_path(tmp_path):
    # a register source value may be a mapping {external_id, vendor_path} (the re-keyed
    # pi_af form: WebId as external_id, AF path as vendor_path); plain strings keep the
    # old behavior (external_id only, vendor_path stays None)
    web_id = P101A_WEBID
    af_path = P101A_AF_PATH
    register = tmp_path / "register.yaml"
    register.write_text(
        "version: 1\n"
        f"tenant_id: {TENANT}\n"
        "plant_id: refinery-gc\n"
        "assets:\n"
        f"  - asset_id: {P101A}\n"
        "    tag: P-101A\n"
        "    unit: unit-101\n"
        "    iso14224_class: pump.centrifugal\n"
        "    iso14224_level: 6\n"
        "    criticality: high\n"
        "    external_ids:\n"
        "      maximo: CRDU-P101A\n"
        "      pi_af:\n"
        f"        external_id: {web_id}\n"
        f"        vendor_path: {af_path}\n")
    repo = InMemoryRepository()
    await seed_from_register(repo, register)

    pi_af = await repo.find_active_alias(TENANT, CONN_PI_AF, web_id, valid_at=None)
    assert pi_af is not None
    assert pi_af.external_id == web_id
    assert pi_af.vendor_path == af_path
    assert pi_af.asset_id == P101A

    maximo = await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=None)
    assert maximo is not None and maximo.vendor_path is None        # string form: back-compat


async def test_seed_rejects_unknown_key_in_external_id_mapping(tmp_path):
    # mapping-form values are authoritative input too: an unknown key is a register bug
    # and must fail loudly, never be silently dropped
    register = tmp_path / "register.yaml"
    register.write_text(
        "version: 1\n"
        f"tenant_id: {TENANT}\n"
        "plant_id: refinery-gc\n"
        "assets:\n"
        f"  - asset_id: {P101A}\n"
        "    tag: P-101A\n"
        "    unit: unit-101\n"
        "    iso14224_class: pump.centrifugal\n"
        "    iso14224_level: 6\n"
        "    criticality: high\n"
        "    external_ids:\n"
        "      pi_af:\n"
        "        external_id: S1abc\n"
        "        vendor_route: oops\n")
    with pytest.raises(ValueError, match="unknown external_ids key"):
        await seed_from_register(InMemoryRepository(), register)


async def test_seed_rejects_mapping_without_external_id(tmp_path):
    register = tmp_path / "register.yaml"
    register.write_text(
        "version: 1\n"
        f"tenant_id: {TENANT}\n"
        "plant_id: refinery-gc\n"
        "assets:\n"
        f"  - asset_id: {P101A}\n"
        "    tag: P-101A\n"
        "    unit: unit-101\n"
        "    iso14224_class: pump.centrifugal\n"
        "    iso14224_level: 6\n"
        "    criticality: high\n"
        "    external_ids:\n"
        "      pi_af:\n"
        "        vendor_path: \\\\PI-DEMO\\Refinery-GC\\X\n")
    with pytest.raises(ValueError, match="missing required key 'external_id'"):
        await seed_from_register(InMemoryRepository(), register)


async def test_seed_creates_connection_rows_and_aliases_fk_them():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)

    # one default connection per legacy source, with the synth ids/categories/statuses
    conns = {c.connection_id: c for c in await repo.list_connections()}
    assert set(conns) == {CONN_MAXIMO, CONN_SAP, CONN_PI_AF, CONN_UNS}
    assert conns[CONN_MAXIMO].category == "cmms" and conns[CONN_MAXIMO].status == "active"
    # sap_pm is parked disabled so it never clashes with maximo on the active cmms slot
    assert conns[CONN_SAP].category == "cmms" and conns[CONN_SAP].status == "disabled"
    assert conns[CONN_PI_AF].category == "hierarchy" and conns[CONN_PI_AF].status == "active"
    assert conns[CONN_UNS].category == "historian" and conns[CONN_UNS].status == "active"
    assert conns[CONN_PI_AF].extra_config == {"database_name": "Refinery-GC"}
    assert all(c.auth_config == {"type": "none", "secret_ref": None} for c in conns.values())

    # every alias FKs one of the synth connections
    by_conn = {a.connection_id: a for a in repo.aliases if a.asset_id == P101A}
    assert set(by_conn) == {CONN_MAXIMO, CONN_SAP, CONN_PI_AF, CONN_UNS}
    assert all(a.connection_id in conns for a in repo.aliases)
    assert all(a.mapping_source == "authoritative_import" for a in by_conn.values())
    assert all(a.resolution_status == "auto_resolved" for a in by_conn.values())
    assert all(a.resolved_by == "system" for a in by_conn.values())
