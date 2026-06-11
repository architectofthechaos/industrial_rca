"""Live-PG test of the breaking 0003 migration (connections + alias rekey).

Skips when DATABASE_URL's server is unreachable. THIS TEST MUTATES THE DEV DB: it
downgrades to base, rebuilds a 0002-shape state with two hand-seeded aliases, runs
`alembic upgrade head` (0003), asserts the connections + rekey landed, then ALWAYS
restores the DB to head in a finally block so reruns and the rest of the suite see a
clean, up-to-date schema.

Run with: `task mar:db` (Postgres) then pytest.
"""
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import text

from rca_mar.config import database_url, make_engine, make_session_factory

MAR_DIR = Path(__file__).resolve().parents[1]
TENANT = uuid4()
PLANT = "refinery-gc"
A1 = uuid4()  # maximo-bound asset
A2 = uuid4()  # pi_af-bound asset


def _pg_reachable() -> bool:
    try:
        u = urlparse(database_url().replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_reachable(),
                                reason="Postgres not reachable (run `task mar:db`)")


def _alembic(*args: str) -> None:
    subprocess.run(["uv", "run", "alembic", *args], cwd=MAR_DIR, check=True,
                   capture_output=True, text=True)


async def _seed_0002_shape() -> None:
    """Insert two assets + two aliases directly with the 0002 (source_system) schema."""
    engine = make_engine()
    sf = make_session_factory(engine)
    async with sf() as s, s.begin():
        for aid, tag, unit in ((A1, "P-101A", "unit-101"), (A2, "P-103A", "unit-201")):
            await s.execute(text(
                "INSERT INTO assets (asset_id, canonical_id, tenant_id, plant_id, "
                "iso14224_class, iso14224_level, tag, criticality, status) "
                "VALUES (:aid, :cid, :tenant, :plant, 'pump.centrifugal', 6, :tag, 'A', "
                "'active')"),
                {"aid": aid, "cid": f"asset:{PLANT}:{unit}:{tag.lower()}", "tenant": TENANT,
                 "plant": PLANT, "tag": tag})
        await s.execute(text(
            "INSERT INTO asset_aliases (alias_id, asset_id, tenant_id, source_system, "
            "source_system_type, external_id, valid_from, mapping_source, confidence, "
            "is_primary, resolution_status) VALUES "
            "(:id1, :a1, :tenant, 'maximo', 'cmms', 'CRDU-P101A', '1970-01-01Z', "
            "'authoritative_import', 1.0, true, 'auto_resolved'), "
            "(:id2, :a2, :tenant, 'pi_af', 'asset_hierarchy', 'WEBID-103A', '1970-01-01Z', "
            "'authoritative_import', 1.0, true, 'auto_resolved')"),
            {"id1": uuid4(), "a1": A1, "id2": uuid4(), "a2": A2, "tenant": TENANT})
    await engine.dispose()


async def _cleanup_seed() -> None:
    engine = make_engine()
    sf = make_session_factory(engine)
    async with sf() as s, s.begin():
        await s.execute(text("DELETE FROM asset_aliases WHERE tenant_id = :t"), {"t": TENANT})
        await s.execute(text("DELETE FROM assets WHERE tenant_id = :t"), {"t": TENANT})
        await s.execute(text(
            "DELETE FROM connections WHERE connection_id LIKE :p"),
            {"p": f"{PLANT}.%-default"})
    await engine.dispose()


async def test_0003_synthesizes_connections_and_rekeys_aliases():
    try:
        # Rebuild a clean 0002-shape DB, then hand-seed the legacy rows.
        _alembic("downgrade", "base")
        _alembic("upgrade", "0002_phase1_alignment")
        await _seed_0002_shape()

        # Apply the breaking migration.
        _alembic("upgrade", "head")

        engine = make_engine()
        sf = make_session_factory(engine)
        async with sf() as s:
            # 1. The two synth connections exist with the right ids/categories/statuses.
            conns = {r["connection_id"]: r for r in (await s.execute(text(
                "SELECT connection_id, plant_id, category, connector_type, status, base_url, "
                "extra_config FROM connections WHERE plant_id = :p"), {"p": PLANT})).mappings()}
            assert set(conns) == {
                f"{PLANT}.cmms.maximo-default", f"{PLANT}.hierarchy.pi-af-default"}
            maximo = conns[f"{PLANT}.cmms.maximo-default"]
            assert maximo["category"] == "cmms" and maximo["status"] == "active"
            assert maximo["connector_type"] == "maximo"
            assert maximo["base_url"] == "http://localhost:8002"
            pi_af = conns[f"{PLANT}.hierarchy.pi-af-default"]
            assert pi_af["category"] == "hierarchy" and pi_af["status"] == "active"
            assert pi_af["base_url"] == "http://localhost:8001"
            assert pi_af["extra_config"] == {"database_name": "Refinery-GC"}

            # 2. Every alias has a non-null connection_id matching its synth connection.
            rows = (await s.execute(text(
                "SELECT external_id, connection_id FROM asset_aliases WHERE tenant_id = :t"),
                {"t": TENANT})).mappings().all()
            by_ext = {r["external_id"]: r["connection_id"] for r in rows}
            assert by_ext == {
                "CRDU-P101A": f"{PLANT}.cmms.maximo-default",
                "WEBID-103A": f"{PLANT}.hierarchy.pi-af-default"}
            assert all(r["connection_id"] is not None for r in rows)

            # 3. The legacy columns are gone.
            cols = {r[0] for r in (await s.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'asset_aliases'"))).all()}
            assert "source_system" not in cols and "source_system_type" not in cols
            assert "connection_id" in cols

        # 4. The partial unique index works: a 2nd ACTIVE cmms connection for the same plant
        #    is rejected; a non-active one is fine.
        async with sf() as s, s.begin():
            with pytest.raises(Exception):  # IntegrityError under the hood
                await s.execute(text(
                    "INSERT INTO connections (connection_id, plant_id, category, connector_type, "
                    "display_name, base_url, auth_config, status) VALUES "
                    "(:cid, :p, 'cmms', 'sap_pm', 'sap (2nd active)', 'http://x', "
                    "CAST('{\"type\":\"none\",\"secret_ref\":null}' AS jsonb), 'active')"),
                    {"cid": f"{PLANT}.cmms.sap-pm-default", "p": PLANT})
        await engine.dispose()
    finally:
        # ALWAYS leave the DB clean + at head for reruns and the rest of the suite.
        await _cleanup_seed()
        _alembic("upgrade", "head")
