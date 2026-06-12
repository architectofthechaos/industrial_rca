"""Proof (Sprint 6 WI3) that the destructive mar suite never touches the LIVE ``rca_mar`` store.

Stack-gated (``RCA_DB=1``). Measures the LIVE store EXPLICITLY via its literal DSN — NOT via
``config.database_url()``, which the package conftest now redirects to ``test_rca_mar``. It
counts live ``assets``, runs the destructive migration test in a subprocess (which inherits the
conftest's redirected env, so it operates on ``test_rca_mar``), then re-counts the live store and
asserts the count is unchanged.

Run with: ``RCA_DB=1 uv run pytest packages/mar/tests/test_live_store_untouched.py -v``
"""
from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_DATABASE_URL = os.environ.get(
    "LIVE_DATABASE_URL", "postgresql+asyncpg://rca:rca@127.0.0.1:5432/rca_mar")

pytestmark = pytest.mark.skipif(
    os.environ.get("RCA_DB") != "1", reason="stack-gated: set RCA_DB=1 to run against the stack")


def _live_reachable() -> bool:
    try:
        u = urlparse(LIVE_DATABASE_URL.replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


async def _live_asset_count() -> int:
    engine = create_async_engine(LIVE_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text("SELECT count(*) FROM assets"))).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _live_reachable(), reason="live Postgres not reachable")
async def test_destructive_migration_test_does_not_touch_live_store():
    before = await _live_asset_count()

    # Run the destructive migration test in a subprocess. It inherits this process's env, where
    # the package conftest's session-autouse fixture has set DATABASE_URL=.../test_rca_mar, so
    # the downgrade/DELETE/rebuild all land on the throwaway DB.
    subprocess.run(
        ["uv", "run", "pytest", "packages/mar/tests/test_migration_0003.py", "-q"],
        cwd=REPO_ROOT, check=True)

    after = await _live_asset_count()
    assert after == before, (
        f"LIVE rca_mar asset count changed ({before} -> {after}); the destructive test leaked "
        f"into the live store")
