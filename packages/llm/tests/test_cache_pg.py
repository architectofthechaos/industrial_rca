"""DB-gated round-trip for the Postgres-backed ResponseCache (Sprint 6 WI5).

SAFETY: the llm test package is NOT covered by the mar conftest's DATABASE_URL redirect, so a
bare ``PostgresResponseCache()`` would hit the LIVE ``rca_mar``. This test instead builds the
cache with an explicit session_factory over the THROWAWAY ``test_rca_cache`` (created + migrated
to head by ``test_db_url`` below). The live store is never touched.

Isolation note: the DB name ``test_rca_cache`` is intentionally DISTINCT from the mar conftest's
``test_rca_mar`` so running the mar suite and this suite in the same pytest session cannot cause
cross-suite DROP interference.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(os.environ.get("RCA_DB") != "1",
                                reason="requires Postgres (task infra:up)")

TEST_DB_NAME = "test_rca_cache"
MAR_DIR = Path(__file__).resolve().parents[2] / "mar"


def _with_db_path(url: str, db_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


@pytest.fixture(scope="module")
def test_db_url() -> Generator[str, None, None]:
    """Create + migrate a throwaway ``test_rca_cache`` to head (so the response_cache table
    exists), yield its URL, then DROP it on teardown.

    Admin DROP/CREATE run against the maintenance ``postgres`` DB so the live ``rca_mar`` is
    never altered. Migration uses the inherited-env alembic subprocess, pointed at the test DB
    via DATABASE_URL.
    """
    from rca_mar.config import database_url

    live_url = database_url()  # e.g. postgresql+asyncpg://rca:rca@127.0.0.1:5432/rca_mar
    admin_url = _with_db_path(live_url, "postgres")
    db_url = _with_db_path(live_url, TEST_DB_NAME)

    async def _recreate() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
                await conn.execute(
                    text(f"CREATE DATABASE {TEST_DB_NAME} TEMPLATE template0"))
        finally:
            await engine.dispose()

    async def _drop() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                # WITH (FORCE) terminates any remaining client connections before dropping
                # (PG 13+). Required because async engines opened during tests may not be
                # fully disposed by the time teardown runs.
                await conn.execute(
                    text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        finally:
            await engine.dispose()

    asyncio.run(_recreate())
    env = dict(os.environ, DATABASE_URL=db_url)
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"],
                   cwd=MAR_DIR, check=True, capture_output=True, text=True, env=env)
    try:
        yield db_url
    finally:
        asyncio.run(_drop())


async def test_pg_cache_roundtrip_across_instances(test_db_url: str) -> None:
    from rca_mar.config import make_engine, make_session_factory

    from rca_llm.cache_pg import PostgresResponseCache

    sf = make_session_factory(make_engine(test_db_url))
    c1 = PostgresResponseCache(session_factory=sf)
    key = "sprint6-wi5-test-deadbeef"
    val = {"content": "X", "structured": {"a": 1}, "model": "m", "model_version": "v",
           "input_tokens": 3, "output_tokens": 4}
    await c1.put(key, val)

    # A fresh instance over a fresh engine on the SAME DB — simulates a new process.
    sf2 = make_session_factory(make_engine(test_db_url))
    c2 = PostgresResponseCache(session_factory=sf2)
    assert await c2.get(key) == val
    assert await c2.get("missing-key-xyz") is None

    # on_conflict_do_nothing => second put with the same key is a no-op (first-write-wins).
    await c2.put(key, {"content": "Y", "structured": None, "model": "m2",
                       "model_version": "v2", "input_tokens": 9, "output_tokens": 9})
    assert await c2.get(key) == val
