"""Test isolation for the MAR DB suite (Sprint 6 WI3).

SAFETY: several mar tests are destructive (``test_migration_0003`` runs ``alembic downgrade
base`` and ``DELETE FROM assets``) and others write rows. Left unchecked they target whatever
``DATABASE_URL`` resolves to — which DEFAULTS to the LIVE ``rca_mar`` store holding seeded
reference-plant assets. This conftest redirects the ENTIRE mar test package at a throwaway
``test_rca_mar`` database for the whole session, so:

  * in-process ``make_engine()`` (reads ``os.environ["DATABASE_URL"]``) hits the test DB, and
  * the ``alembic`` subprocess (inherits ``os.environ``) also hits the test DB.

The redirect is an ``os.environ`` save/restore in a session-scoped autouse fixture — the
simplest mechanism that is guaranteed to reach subprocesses (pytest's ``monkeypatch`` is
function-scoped and cannot be used at session scope). A defense-in-depth ``assert_test_database``
guard in ``test_migration_0003`` makes any destructive op fail fast if the redirect ever lapses.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from rca_mar.config import database_url

MAR_DIR = Path(__file__).resolve().parents[1]
TEST_DB_NAME = "test_rca_mar"


def _pg_reachable() -> bool:
    """Socket probe of the PG server behind the *default/live* DATABASE_URL (same server we
    create the throwaway DB on). Mirrors the per-test ``_pg_reachable`` checks."""
    try:
        u = urlparse(database_url().replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


def _with_db_path(url: str, db_name: str) -> str:
    """Return ``url`` with its path (database name) swapped to ``db_name``."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


def _test_db_url() -> str:
    return _with_db_path(database_url(), TEST_DB_NAME)


def _admin_url() -> str:
    """The maintenance ``postgres`` DB on the same server (can't DROP/CREATE while connected to
    the target DB)."""
    return _with_db_path(database_url(), "postgres")


async def _recreate_test_db() -> None:
    engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
            # Clone from template0 (not the default template1): template1 can carry a
            # collation-version mismatch (DB built under a different libc/ICU than the host),
            # which makes a plain CREATE DATABASE refuse. template0 sidesteps that and gives a
            # pristine schema we migrate to head anyway.
            await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME} TEMPLATE template0"))
    finally:
        await engine.dispose()


async def _drop_test_db() -> None:
    engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def mar_test_db() -> Generator[str, None, None]:
    """Create a fresh throwaway ``test_rca_mar`` for the session; drop it on teardown.

    Admin (DROP/CREATE) ops run via ``asyncio.run`` on their own loop — outside any test loop,
    which is fine since they touch the maintenance DB, not the test DB. When PG is unreachable
    we still yield the test URL; the DB-touching tests skip themselves via their own
    ``_pg_reachable`` guards, so the hermetic suite stays green.
    """
    reachable = _pg_reachable()
    if reachable:
        asyncio.run(_recreate_test_db())
    try:
        yield _test_db_url()
    finally:
        if reachable:
            asyncio.run(_drop_test_db())


@pytest.fixture(scope="session", autouse=True)
def _redirect_database_url(mar_test_db: str) -> Generator[None, None, None]:
    """Point the whole mar test package at the throwaway DB for the session.

    ``os.environ`` save/restore (not pytest ``monkeypatch``, which is function-scoped) so the
    redirect reaches BOTH in-process engines AND the inherited-env ``alembic`` subprocess. When
    PG is reachable, migrate the fresh DB to head once so DB-reading tests see a head schema.
    """
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = mar_test_db
    try:
        if _pg_reachable():
            subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=MAR_DIR, check=True, capture_output=True, text=True,
            )
        yield
    finally:
        if saved is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved
