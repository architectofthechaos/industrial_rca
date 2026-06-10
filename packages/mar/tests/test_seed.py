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


async def test_seed_populates_assets_and_aliases():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)

    p101a = await repo.get_asset(TENANT, P101A)
    assert p101a is not None and p101a.tag == "P-101A"
    assert p101a.criticality == "A"                 # high -> A mapping
    assert p101a.plant_id == "refinery-gc"

    assert await repo.source_handle_for(TENANT, P101A, "maximo") == "CRDU-P101A"
    assert await repo.source_handle_for(TENANT, P101A, "sap_pm") == "10001234"
    assert await repo.source_handle_for(TENANT, P101A, "pi_af") == r"\\PI-DEMO\Refinery\P-101A"
    assert await repo.source_handle_for(TENANT, P101A, "uns") == "crude.p101a"


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


async def test_seed_aliases_carry_source_system_type():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    by_source = {a.source_system: a for a in repo.aliases if a.asset_id == P101A}
    assert by_source["maximo"].source_system_type == "cmms"
    assert by_source["sap_pm"].source_system_type == "cmms"
    assert by_source["pi_af"].source_system_type == "asset_hierarchy"
    assert by_source["uns"].source_system_type == "historian"
    assert all(a.mapping_source == "authoritative_import" for a in by_source.values())
    assert all(a.resolution_status == "auto_resolved" for a in by_source.values())
    assert all(a.resolved_by == "system" for a in by_source.values())
