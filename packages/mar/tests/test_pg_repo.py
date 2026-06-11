"""PostgresRepository against a REAL Postgres. Skips when DATABASE_URL's server is unreachable.
Run with: `task mar:db`."""
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from rca_contracts import AssetDescriptor

from rca_mar.config import database_url, make_engine, make_session_factory
from rca_mar.repository import AliasRow, ConnectionRow
from rca_mar.repository_pg import PostgresRepository

TENANT = uuid4()


def _pg_reachable() -> bool:
    try:
        u = urlparse(database_url().replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_reachable(),
                                reason="Postgres not reachable (run `task mar:db`)")


def _asset(asset_id, tag):
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=f"asset:refinery-gc:unit-101:{tag.lower()}",
        tenant_id=TENANT, plant_id="refinery-gc",
        iso14224_class="pump.centrifugal", iso14224_level=6, tag=tag, service=None,
        criticality="A", manufacturer=None, model=None, serial_number=None,
        commissioned_at=None, decommissioned_at=None, location_description=None, description=None)


async def _make_connection(repo, *, category="cmms", connector_type="maximo",
                           base_url="http://localhost:8002", status="pending") -> str:
    """Upsert a unique-id connection (status pending so concurrent tests never collide on the
    one-active-per-(plant, category) partial unique index) and return its id. Aliases FK it."""
    cid = f"refinery-gc.{category}.{connector_type.replace('_', '-')}-{uuid4().hex[:8]}"
    await repo.upsert_connection(ConnectionRow(
        connection_id=cid, plant_id="refinery-gc", category=category,
        connector_type=connector_type, display_name=f"{connector_type} (test)",
        base_url=base_url, auth_config={"type": "none", "secret_ref": None}, status=status))
    return cid


async def test_pg_roundtrip_and_canonical_lookup():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    pump = uuid4()
    tag = f"P-{pump.hex[:6].upper()}"
    await repo.upsert_asset(_asset(pump, tag))
    conn = await _make_connection(repo)
    await repo.upsert_alias(AliasRow(pump, TENANT, conn, f"LOC-{pump.hex[:6]}",
                                     datetime(2020, 1, 1, tzinfo=timezone.utc), None,
                                     "authoritative_import", 1.0, True))

    got = await repo.get_asset(TENANT, pump)
    assert got is not None and got.canonical_id == f"asset:refinery-gc:unit-101:{tag.lower()}"
    by_canonical = await repo.find_asset_by_canonical_id(
        TENANT, f"asset:refinery-gc:unit-101:{tag.lower()}")
    assert by_canonical is not None and by_canonical.asset_id == pump
    assert await repo.source_handle_for(TENANT, pump, conn) == f"LOC-{pump.hex[:6]}"
    hits = await repo.search_assets(TENANT, canonical_id_pattern=f"%{tag.lower()}%")
    assert [a.asset_id for a in hits] == [pump]
    await engine.dispose()


async def test_pg_alias_resolution_metadata_roundtrip():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    pump = uuid4()
    await repo.upsert_asset(_asset(pump, f"P-{pump.hex[:6].upper()}"))
    conn = await _make_connection(repo, category="historian", connector_type="uns",
                                  base_url="mqtt://localhost:1883")
    await repo.upsert_alias(AliasRow(
        pump, TENANT, conn, f"site.{pump.hex[:6]}.pv",
        datetime(2026, 1, 1, tzinfo=timezone.utc), None, "rule:tag_pattern", 0.7, False,
        resolution_status="pending_review",
        candidate_alternatives=[{"canonical_id": "asset:refinery-gc:unit-101:x",
                                 "confidence": 0.7, "method": "rule:tag_pattern"}],
        resolved_by="system"))
    row = await repo.find_active_alias(TENANT, conn, f"site.{pump.hex[:6]}.pv", valid_at=None)
    assert row is not None and row.resolution_status == "pending_review"
    assert row.connection_id == conn and row.resolved_by == "system"
    assert row.candidate_alternatives[0]["method"] == "rule:tag_pattern"
    await engine.dispose()


async def test_pg_upsert_alias_supersede_and_temporal():
    """Re-pointing an external_id closes the prior active alias and opens a new one (the
    partial-unique active constraint holds), and historical valid_at still resolves to the
    asset that owned the id at that time (asset-rename temporal validity)."""
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    a1, a2 = uuid4(), uuid4()
    ext = f"EXT-{uuid4().hex[:8]}"
    await repo.upsert_asset(_asset(a1, f"P-{a1.hex[:6]}"))
    await repo.upsert_asset(_asset(a2, f"P-{a2.hex[:6]}"))
    conn = await _make_connection(repo)
    t2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    t2021 = datetime(2021, 1, 1, tzinfo=timezone.utc)

    await repo.upsert_alias(AliasRow(a1, TENANT, conn, ext, t2020, None,
                                     "authoritative_import", 1.0, True))
    assert (await repo.find_active_alias(TENANT, conn, ext, valid_at=None)).asset_id == a1

    # supersede -> a2 (closes a1's active row at 2021, inserts a2 open). Only one active row.
    await repo.upsert_alias(AliasRow(a2, TENANT, conn, ext, t2021, None,
                                     "manual", 1.0, True,
                                     resolution_status="human_validated"))
    assert (await repo.find_active_alias(TENANT, conn, ext, valid_at=None)).asset_id == a2

    # historical query before the rename still resolves to a1 (temporal validity)
    mid2020 = datetime(2020, 6, 1, tzinfo=timezone.utc)
    assert (await repo.find_active_alias(TENANT, conn, ext, valid_at=mid2020)).asset_id == a1
    await engine.dispose()


async def test_pg_upsert_asset_updated_at_refreshes():
    """Upserting the same asset twice must bump updated_at (proves on_conflict func.now()
    at repository_pg.py:50)."""
    from sqlalchemy import select
    from rca_mar.models import Asset

    engine = make_engine()
    session_factory = make_session_factory(engine)
    repo = PostgresRepository(session_factory)
    pump = uuid4()
    tag = f"P-{pump.hex[:6].upper()}"
    asset = _asset(pump, tag)

    await repo.upsert_asset(asset)
    async with session_factory() as s:
        row1 = (await s.execute(select(Asset).where(Asset.asset_id == pump))).scalar_one()
        updated_at_first = row1.updated_at

    await repo.upsert_asset(asset)
    async with session_factory() as s:
        row2 = (await s.execute(select(Asset).where(Asset.asset_id == pump))).scalar_one()
        updated_at_second = row2.updated_at

    assert updated_at_second >= updated_at_first
    await engine.dispose()
