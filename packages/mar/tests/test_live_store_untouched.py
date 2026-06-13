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

from rca_mar.config import DEFAULT_URL as _LIVE_DEFAULT

REPO_ROOT = Path(__file__).resolve().parents[3]
# Live store is the config DEFAULT (NOT database_url(), which conftest redirects to test_rca_mar).
LIVE_DATABASE_URL = os.environ.get("LIVE_DATABASE_URL", _LIVE_DEFAULT)

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

    # Run the destructive migration test in a subprocess. The child starts its OWN pytest session
    # which reloads the mar conftest, whose session-scoped fixtures CREATE the throwaway DB on
    # setup and DROP it on teardown. If the child used the same name as the parent
    # (``test_rca_mar``), its teardown DROP would destroy the parent session's shared DB mid-run.
    # So point the child at a DISTINCT throwaway DB via MAR_TEST_DB; the child's conftest computes
    # its test URL from that name and resets DATABASE_URL itself before any DB-touching test runs.
    # The downgrade/DELETE/rebuild all land on the child's own ``test_rca_mar_subproc``.
    env = {**os.environ, "MAR_TEST_DB": "test_rca_mar_subproc"}
    subprocess.run(
        ["uv", "run", "pytest", "packages/mar/tests/test_migration_0003.py", "-q"],
        cwd=REPO_ROOT, check=True, env=env)

    after = await _live_asset_count()
    assert after == before, (
        f"LIVE rca_mar asset count changed ({before} -> {after}); the destructive test leaked "
        f"into the live store")
