from datetime import datetime, timezone
from uuid import uuid4

from rca_contracts import AssetDescriptor

from rca_mar.repository import AliasRow, InMemoryRepository

TENANT = uuid4()


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
    await repo.upsert_alias(AliasRow(
        asset_id=pump, tenant_id=TENANT, source_system="maximo", external_id="CRDU-P101A",
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc), valid_to=None,
        mapping_source="authoritative_import", confidence=1.0, is_primary=True))
    return repo, pump, other


async def test_find_active_alias():
    repo, pump, _other = await _repo()
    row = await repo.find_active_alias(TENANT, "maximo", "CRDU-P101A", valid_at=None)
    assert row is not None and row.asset_id == pump


async def test_find_active_alias_respects_valid_at_for_open_alias():
    # The seeded alias is open-ended with valid_from=2020-01-01. A valid_at BEFORE valid_from
    # must NOT match (mirrors the Postgres predicate — guards the InMemory/PG parity).
    repo, pump, _other = await _repo()
    before = datetime(2019, 1, 1, tzinfo=timezone.utc)
    after = datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert await repo.find_active_alias(TENANT, "maximo", "CRDU-P101A", valid_at=before) is None
    row = await repo.find_active_alias(TENANT, "maximo", "CRDU-P101A", valid_at=after)
    assert row is not None and row.asset_id == pump


async def test_source_handle_for_reverse_lookup():
    repo, pump, _other = await _repo()
    assert await repo.source_handle_for(TENANT, pump, "maximo") == "CRDU-P101A"
    assert await repo.source_handle_for(TENANT, pump, "sap_pm") is None


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
        asset_id=other, tenant_id=TENANT, source_system="maximo", external_id="CRDU-P101A",
        valid_from=t2021, valid_to=None, mapping_source="manual", confidence=1.0,
        is_primary=True, resolution_status="human_validated"))

    active = await repo.find_active_alias(TENANT, "maximo", "CRDU-P101A", valid_at=None)
    assert active is not None and active.asset_id == other

    closed = [a for a in repo.aliases if a.valid_to is not None]
    assert len(closed) == 1 and closed[0].asset_id == pump and closed[0].valid_to == t2021

    mid2020 = datetime(2020, 6, 1, tzinfo=timezone.utc)
    historical = await repo.find_active_alias(TENANT, "maximo", "CRDU-P101A", valid_at=mid2020)
    assert historical is not None and historical.asset_id == pump


async def test_unresolved_upsert_counts():
    repo, *_ = await _repo()
    await repo.upsert_unresolved(TENANT, "sap_pm", "99999", {"hint": "x"})
    await repo.upsert_unresolved(TENANT, "sap_pm", "99999", {"hint": "x"})
    assert repo.unresolved[(TENANT, "sap_pm", "99999")]["occurrence_count"] == 2
