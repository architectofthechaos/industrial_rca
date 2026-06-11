from datetime import datetime, timezone
from uuid import uuid4

import pytest
from rca_contracts import AssetDescriptor

from rca_mar.repository import (
    AliasRow,
    ConnectionRow,
    DuplicateActiveConnection,
    InMemoryRepository,
)

TENANT = uuid4()
CONN_MAXIMO = "refinery-gc.cmms.maximo-default"
CONN_SAP = "refinery-gc.cmms.sap-pm-default"


def _conn(connection_id, category, status="active", plant_id="refinery-gc",
          connector_type="maximo") -> ConnectionRow:
    return ConnectionRow(
        connection_id=connection_id, plant_id=plant_id, category=category,
        connector_type=connector_type, display_name=f"{connector_type} (default)",
        base_url="http://localhost:8002", auth_config={"type": "none", "secret_ref": None},
        status=status)


def _asset(asset_id, tag) -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=f"asset:refinery-gc:unit-101:{tag.lower()}",
        tenant_id=TENANT, plant_id="refinery-gc",
        iso14224_class="pump.centrifugal", iso14224_level=6, tag=tag,
        service=None, criticality="A", manufacturer=None, model=None,
        serial_number=None, commissioned_at=None, decommissioned_at=None,
        location_description=None, description=None,
    )


async def _repo():
    repo = InMemoryRepository()
    pump = uuid4()
    other = uuid4()
    await repo.upsert_asset(_asset(pump, "P-101A"))
    await repo.upsert_asset(_asset(other, "P-103A"))
    await repo.upsert_connection(_conn(CONN_MAXIMO, "cmms"))
    await repo.upsert_alias(AliasRow(
        asset_id=pump, tenant_id=TENANT, connection_id=CONN_MAXIMO, external_id="CRDU-P101A",
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc), valid_to=None,
        mapping_source="authoritative_import", confidence=1.0, is_primary=True))
    return repo, pump, other


async def test_find_active_alias():
    repo, pump, _other = await _repo()
    row = await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=None)
    assert row is not None and row.asset_id == pump


async def test_find_active_alias_respects_valid_at_for_open_alias():
    # The seeded alias is open-ended with valid_from=2020-01-01. A valid_at BEFORE valid_from
    # must NOT match (mirrors the Postgres predicate — guards the InMemory/PG parity).
    repo, pump, _other = await _repo()
    before = datetime(2019, 1, 1, tzinfo=timezone.utc)
    after = datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=before) is None
    row = await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=after)
    assert row is not None and row.asset_id == pump


async def test_source_handle_for_reverse_lookup():
    repo, pump, _other = await _repo()
    assert await repo.source_handle_for(TENANT, pump, CONN_MAXIMO) == "CRDU-P101A"
    assert await repo.source_handle_for(TENANT, pump, CONN_SAP) is None


async def test_find_asset_by_tag_and_get():
    repo, pump, _other = await _repo()
    a = await repo.find_asset_by_tag(TENANT, "P-101A")
    assert a is not None and a.asset_id == pump
    assert (await repo.get_asset(TENANT, pump)).tag == "P-101A"
    assert await repo.get_asset(TENANT, uuid4()) is None


async def test_find_asset_by_canonical_id():
    repo, pump, _other = await _repo()
    a = await repo.find_asset_by_canonical_id(TENANT, "asset:refinery-gc:unit-101:p-101a")
    assert a is not None and a.asset_id == pump
    assert await repo.find_asset_by_canonical_id(TENANT, "asset:nope:unit-1:x-1") is None
    assert await repo.find_asset_by_canonical_id(uuid4(), "asset:refinery-gc:unit-101:p-101a") is None


async def test_search_by_canonical_id_pattern():
    repo, pump, other = await _repo()
    hits = await repo.search_assets(TENANT, canonical_id_pattern="asset:refinery-gc:unit-101:%")
    assert {a.asset_id for a in hits} == {pump, other}
    hits = await repo.search_assets(TENANT, canonical_id_pattern="%p-103a%")
    assert [a.asset_id for a in hits] == [other]


async def test_canonical_id_pattern_regex_metacharacter_treated_literally():
    # _like_to_regex must escape regex metacharacters: pattern '%p.101a%' must NOT match
    # 'asset:refinery-gc:unit-101:p-101a' (the dot in the LIKE pattern is a literal dot, not
    # a regex wildcard).  Guarding against re.escape omission in _like_to_regex.
    repo, pump, _other = await _repo()
    # 'p.101a' dot is literal -> no match against 'p-101a'
    hits = await repo.search_assets(TENANT, canonical_id_pattern="%p.101a%")
    assert hits == []
    # but the real pattern still matches
    hits = await repo.search_assets(TENANT, canonical_id_pattern="%p-101a%")
    assert [a.asset_id for a in hits] == [pump]


async def test_canonical_id_pattern_uses_like_semantics_not_substring():
    # PG parity: LIKE is anchored — a wildcard-free pattern is an exact match, NOT substring
    repo, pump, other = await _repo()
    assert await repo.search_assets(TENANT, canonical_id_pattern="p-101a") == []
    hits = await repo.search_assets(TENANT, canonical_id_pattern="%p-101a")
    assert [a.asset_id for a in hits] == [pump]
    # '_' matches exactly one character, as in SQL LIKE
    hits = await repo.search_assets(TENANT,
                                    canonical_id_pattern="asset:refinery-gc:unit-101:p-10_a")
    assert {a.asset_id for a in hits} == {pump, other}


async def test_upsert_alias_supersede_closes_previous_and_keeps_history():
    # In-memory analogue of test_pg_repo.test_pg_upsert_alias_supersede_and_temporal:
    # re-pointing an external_id CLOSES the prior active row (valid_to = new valid_from)
    # instead of deleting it, so historical valid_at lookups still resolve.
    repo, pump, other = await _repo()
    t2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)
    await repo.upsert_alias(AliasRow(
        asset_id=other, tenant_id=TENANT, connection_id=CONN_MAXIMO, external_id="CRDU-P101A",
        valid_from=t2021, valid_to=None, mapping_source="manual", confidence=1.0,
        is_primary=True, resolution_status="human_validated"))

    active = await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=None)
    assert active is not None and active.asset_id == other

    closed = [a for a in repo.aliases if a.valid_to is not None]
    assert len(closed) == 1 and closed[0].asset_id == pump and closed[0].valid_to == t2021

    mid2020 = datetime(2020, 6, 1, tzinfo=timezone.utc)
    historical = await repo.find_active_alias(TENANT, CONN_MAXIMO, "CRDU-P101A", valid_at=mid2020)
    assert historical is not None and historical.asset_id == pump


async def test_unresolved_upsert_counts():
    repo, *_ = await _repo()
    await repo.upsert_unresolved(TENANT, "sap_pm", "99999", {"hint": "x"})
    await repo.upsert_unresolved(TENANT, "sap_pm", "99999", {"hint": "x"})
    assert repo.unresolved[(TENANT, "sap_pm", "99999")]["occurrence_count"] == 2


async def test_connection_crud_roundtrip():
    repo = InMemoryRepository()
    conn = _conn(CONN_MAXIMO, "cmms", status="pending")
    await repo.upsert_connection(conn)
    assert await repo.get_connection(CONN_MAXIMO) == conn
    # upsert is idempotent + updates in place
    updated = _conn(CONN_MAXIMO, "cmms", status="active")
    await repo.upsert_connection(updated)
    assert (await repo.get_connection(CONN_MAXIMO)).status == "active"
    assert await repo.get_connection("nope") is None
    await repo.delete_connection(CONN_MAXIMO)
    assert await repo.get_connection(CONN_MAXIMO) is None


async def test_list_connections_filters():
    repo = InMemoryRepository()
    await repo.upsert_connection(_conn(CONN_MAXIMO, "cmms", status="active"))
    await repo.upsert_connection(_conn("refinery-gc.historian.uns-default", "historian",
                                       status="pending", connector_type="uns"))
    await repo.upsert_connection(_conn("plant-b.cmms.maximo-default", "cmms",
                                       status="active", plant_id="plant-b"))
    assert {c.connection_id for c in await repo.list_connections(plant_id="refinery-gc")} == {
        CONN_MAXIMO, "refinery-gc.historian.uns-default"}
    assert {c.connection_id for c in await repo.list_connections(category="cmms")} == {
        CONN_MAXIMO, "plant-b.cmms.maximo-default"}
    assert {c.connection_id for c in await repo.list_connections(status="pending")} == {
        "refinery-gc.historian.uns-default"}


async def test_count_aliases_for_connection():
    repo, pump, _other = await _repo()
    assert await repo.count_aliases_for_connection(CONN_MAXIMO) == 1
    assert await repo.count_aliases_for_connection("nope") == 0


async def test_one_active_per_category_raises_duplicate_active():
    # the in-memory repo enforces the partial-unique invariant the live DB enforces via
    # uq_connection_active_category: a 2nd active connection for the same (plant, category)
    repo = InMemoryRepository()
    await repo.upsert_connection(_conn(CONN_MAXIMO, "cmms", status="active"))
    with pytest.raises(DuplicateActiveConnection) as exc:
        await repo.upsert_connection(_conn(CONN_SAP, "cmms", status="active",
                                           connector_type="sap_pm"))
    assert exc.value.existing_connection_id == CONN_MAXIMO
    assert exc.value.category == "cmms"
    # a disabled second connection in the same category is fine
    await repo.upsert_connection(_conn(CONN_SAP, "cmms", status="disabled",
                                       connector_type="sap_pm"))
    # re-upserting the SAME active connection is not a conflict with itself
    await repo.upsert_connection(_conn(CONN_MAXIMO, "cmms", status="active"))
    # a different category can also be active
    await repo.upsert_connection(_conn("refinery-gc.historian.uns-default", "historian",
                                       status="active", connector_type="uns"))
