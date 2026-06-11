"""Resolution Queue repository write paths (Sprint 2b §4.1).

Validate/reject/supersede + list_pending_bindings + resolution_stats, with their idempotency
and transition invariants. The InMemory path is hermetic; the same scenarios run against a
live Postgres via the parity skip-when-unreachable pattern (mirrors test_pg_repo.py).
"""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from rca_contracts import AssetDescriptor

from rca_mar.config import database_url, make_engine, make_session_factory
from rca_mar.repository import (
    AliasRow,
    ConnectionRow,
    InMemoryRepository,
    InvalidTransition,
)
from rca_mar.repository_pg import PostgresRepository

TENANT = uuid4()
CONN = "refinery-gc.cmms.maximo-default"


def _asset(asset_id, tag, plant_id="refinery-gc") -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=f"asset:{plant_id}:unit-101:{tag.lower()}",
        tenant_id=TENANT, plant_id=plant_id,
        iso14224_class="pump.centrifugal", iso14224_level=6, tag=tag,
        service=None, criticality="A", manufacturer=None, model=None,
        serial_number=None, commissioned_at=None, decommissioned_at=None,
        location_description=None, description=None)


def _conn(connection_id, plant_id="refinery-gc") -> ConnectionRow:
    return ConnectionRow(
        connection_id=connection_id, plant_id=plant_id, category="cmms",
        connector_type="maximo", display_name="maximo", base_url="http://localhost:8002",
        auth_config={"type": "none", "secret_ref": None}, status="active")


def _pending_alias(asset_id, connection_id=CONN, external_id="CRDU-P101A",
                   candidates=None) -> AliasRow:
    return AliasRow(
        asset_id=asset_id, tenant_id=TENANT, connection_id=connection_id,
        external_id=external_id, valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=None, mapping_source="cross_walk", confidence=0.7, is_primary=False,
        resolution_status="pending_review", resolved_by="system",
        candidate_alternatives=candidates or [
            {"canonical_id": "asset:refinery-gc:unit-101:p-101a", "confidence": 0.7,
             "method": "cross_walk"}])


# ---------------------------------------------------------------------------
# In-memory hermetic coverage
# ---------------------------------------------------------------------------

async def _seed_pending(repo, asset_id=None) -> tuple[InMemoryRepository, object]:
    asset_id = asset_id or uuid4()
    await repo.upsert_asset(_asset(asset_id, "P-101A"))
    await repo.upsert_connection(_conn(CONN))
    await repo.upsert_alias(_pending_alias(asset_id))
    pending = (await repo.list_pending_bindings(TENANT))[0]
    return repo, pending


async def test_validate_sets_human_validated_and_is_idempotent():
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    row = await repo.validate_binding(pending.alias_id, "jane")
    assert row.resolution_status == "human_validated"
    assert row.validated_by == "jane" and row.validated_at is not None
    first_validated_at = row.validated_at
    # idempotent: a second validate returns the row unchanged (same stamp, no churn)
    again = await repo.validate_binding(pending.alias_id, "someone-else")
    assert again.resolution_status == "human_validated"
    assert again.validated_by == "jane" and again.validated_at == first_validated_at


async def test_validate_from_rejected_or_superseded_raises_invalid_transition():
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    await repo.reject_binding(pending.alias_id, "jane", "wrong asset")
    with pytest.raises(InvalidTransition):
        await repo.validate_binding(pending.alias_id, "jane")

    repo2 = InMemoryRepository()
    _, pending2 = await _seed_pending(repo2)
    await repo2.supersede_binding(pending2.alias_id, system_initiated=True)
    with pytest.raises(InvalidTransition):
        await repo2.validate_binding(pending2.alias_id, "jane")


async def test_reject_closes_valid_to_sets_status_and_appends_reason():
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    row = await repo.reject_binding(pending.alias_id, "jane", "not a real tag")
    assert row.resolution_status == "rejected"
    assert row.valid_to is not None
    assert row.validated_by == "jane"
    assert "rejected: not a real tag" in row.notes
    # idempotent re-reject is a no-op (original stamp/notes preserved)
    again = await repo.reject_binding(pending.alias_id, "bob", "second reason")
    assert again.validated_by == "jane"
    assert again.notes.count("rejected:") == 1


async def test_rejected_cannot_become_auto_resolved():
    # A binding cannot be re-opened to auto_resolved from rejected — the only forward move is a
    # NEW binding. validate_binding refuses, and resolve_asset never auto-demotes/promotes a
    # rejected row back (the active-alias lookup ignores it: valid_to is closed).
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    await repo.reject_binding(pending.alias_id, "jane", "bad")
    rejected = await repo.get_alias(pending.alias_id)
    assert rejected.resolution_status == "rejected"
    with pytest.raises(InvalidTransition):
        await repo.validate_binding(pending.alias_id, "jane")
    # find_active_alias must not surface the rejected (closed) row
    assert await repo.find_active_alias(TENANT, CONN, "CRDU-P101A", valid_at=None) is None


async def test_supersede_closes_valid_to_system_and_manual():
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    row = await repo.supersede_binding(pending.alias_id, system_initiated=True)
    assert row.resolution_status == "superseded" and row.valid_to is not None
    assert "(system)" in row.notes
    # idempotent
    again = await repo.supersede_binding(pending.alias_id, system_initiated=True)
    assert again.resolution_status == "superseded"

    repo2 = InMemoryRepository()
    _, pending2 = await _seed_pending(repo2)
    by_id = uuid4()
    row2 = await repo2.supersede_binding(pending2.alias_id, superseded_by_alias_id=by_id)
    assert row2.resolution_status == "superseded" and row2.valid_to is not None
    assert str(by_id) in row2.notes and "(review)" in row2.notes


async def test_list_pending_bindings_filters_and_surfaces_candidates():
    repo = InMemoryRepository()
    a1, a2, a3 = uuid4(), uuid4(), uuid4()
    await repo.upsert_asset(_asset(a1, "P-101A", plant_id="refinery-gc"))
    await repo.upsert_asset(_asset(a2, "P-201A", plant_id="plant-b"))
    await repo.upsert_asset(_asset(a3, "P-301A", plant_id="refinery-gc"))
    await repo.upsert_connection(_conn(CONN))
    await repo.upsert_connection(_conn("plant-b.cmms.maximo-default", plant_id="plant-b"))
    await repo.upsert_alias(_pending_alias(a1, external_id="E1"))
    await repo.upsert_alias(_pending_alias(a2, connection_id="plant-b.cmms.maximo-default",
                                           external_id="E2"))
    await repo.upsert_alias(_pending_alias(a3, external_id="E3"))

    all_pending = await repo.list_pending_bindings(TENANT)
    assert len(all_pending) == 3
    assert all(p.candidate_alternatives for p in all_pending)

    by_conn = await repo.list_pending_bindings(TENANT, connection_id=CONN)
    assert {p.asset_id for p in by_conn} == {a1, a3}

    by_plant = await repo.list_pending_bindings(TENANT, plant_id="plant-b")
    assert {p.asset_id for p in by_plant} == {a2}

    assert len(await repo.list_pending_bindings(TENANT, limit=1)) == 1


async def test_list_pending_excludes_closed_and_non_pending():
    repo = InMemoryRepository()
    _, pending = await _seed_pending(repo)
    assert len(await repo.list_pending_bindings(TENANT)) == 1
    await repo.validate_binding(pending.alias_id, "jane")
    # validated rows are no longer pending
    assert await repo.list_pending_bindings(TENANT) == []


async def test_resolution_stats_counts_by_connection_and_status():
    repo = InMemoryRepository()
    a1, a2 = uuid4(), uuid4()
    await repo.upsert_asset(_asset(a1, "P-101A"))
    await repo.upsert_asset(_asset(a2, "P-102A"))
    await repo.upsert_connection(_conn(CONN))
    await repo.upsert_alias(_pending_alias(a1, external_id="E1"))
    p2 = await repo.list_pending_bindings(TENANT)  # capture E1 alias for later transition
    await repo.upsert_alias(_pending_alias(a2, external_id="E2"))
    # validate one so the stats show two statuses for the same connection
    await repo.validate_binding(p2[0].alias_id, "jane")

    stats = await repo.resolution_stats(TENANT)
    by_status = {s["resolution_status"]: s["count"] for s in stats
                 if s["connection_id"] == CONN}
    assert by_status == {"pending_review": 1, "human_validated": 1}


# ---------------------------------------------------------------------------
# Postgres parity (skips when unreachable)
# ---------------------------------------------------------------------------

def _pg_reachable() -> bool:
    try:
        u = urlparse(database_url().replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


pg = pytest.mark.skipif(not _pg_reachable(), reason="Postgres not reachable (run `task mar:db`)")


async def _pg_seed_pending(repo) -> tuple[object, str]:
    asset_id = uuid4()
    tag = f"P-{asset_id.hex[:6].upper()}"
    await repo.upsert_asset(_asset(asset_id, tag))
    cid = f"refinery-gc.cmms.maximo-{asset_id.hex[:8]}"
    await repo.upsert_connection(ConnectionRow(
        connection_id=cid, plant_id="refinery-gc", category="cmms", connector_type="maximo",
        display_name="maximo", base_url="http://localhost:8002",
        auth_config={"type": "none", "secret_ref": None}, status="pending"))
    ext = f"EXT-{asset_id.hex[:8]}"
    await repo.upsert_alias(_pending_alias(asset_id, connection_id=cid, external_id=ext))
    row = await repo.find_active_alias(TENANT, cid, ext, valid_at=None)
    return row, cid


@pg
async def test_pg_validate_idempotent_and_invalid_transition():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    row, _cid = await _pg_seed_pending(repo)

    validated = await repo.validate_binding(row.alias_id, "jane")
    assert validated.resolution_status == "human_validated"
    assert validated.validated_by == "jane" and validated.validated_at is not None
    again = await repo.validate_binding(row.alias_id, "bob")
    assert again.validated_by == "jane"  # idempotent, no re-stamp

    row2, _cid2 = await _pg_seed_pending(repo)
    await repo.reject_binding(row2.alias_id, "jane", "bad")
    with pytest.raises(InvalidTransition):
        await repo.validate_binding(row2.alias_id, "jane")
    await engine.dispose()


@pg
async def test_pg_reject_and_supersede_close_valid_to():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    row, _cid = await _pg_seed_pending(repo)
    rejected = await repo.reject_binding(row.alias_id, "jane", "wrong")
    assert rejected.resolution_status == "rejected" and rejected.valid_to is not None
    assert "rejected: wrong" in rejected.notes

    row2, _cid2 = await _pg_seed_pending(repo)
    sup = await repo.supersede_binding(row2.alias_id, system_initiated=True)
    assert sup.resolution_status == "superseded" and sup.valid_to is not None
    await engine.dispose()


@pg
async def test_pg_list_pending_and_stats():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    row, cid = await _pg_seed_pending(repo)
    pending = await repo.list_pending_bindings(TENANT, connection_id=cid)
    assert len(pending) == 1 and pending[0].candidate_alternatives
    stats = await repo.resolution_stats(TENANT)
    assert any(s["connection_id"] == cid and s["resolution_status"] == "pending_review"
               and s["count"] == 1 for s in stats)
    await engine.dispose()
