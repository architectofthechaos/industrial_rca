"""Cross-process LLM determinism replay via the Postgres-backed ResponseCache (Sprint 6 WI5).

The InMemoryResponseCache only replays within ONE process. PostgresResponseCache persists the
content-addressed response so a RECORD run and a later REPLAY run (e.g. separate Temporal
activities, or a re-run after a restart) replay byte-identically with NO upstream call.

Two proofs here, both gated by ``RCA_DB=1``:

  * ``test_xprocess_determinism_two_instances`` (RUNNABLE) — the cross-instance proof. Two
    independent ``PostgresResponseCache`` instances over independent engines on the same DB:
    instance A records with a scripted transport; instance B (fresh engine) replays with
    ``NoUpstreamTransport`` + ``replay_from_cache=True`` and asserts byte-identical
    content/structured. This proves the cache crosses the client-instance boundary (the only
    state shared is the DB), which is what cross-process replay relies on. Modelled on
    ``packages/llm/tests/test_client.py::test_replay_from_cache_returns_cached_with_no_upstream_call``.

  * ``test_xprocess_determinism_subprocess`` (also gated) — the true two-PROCESS proof. Process
    A (a fresh interpreter) records; process B (another fresh interpreter) replays. Heavier and
    slower; kept gated alongside the in-process proof. If PG is unreachable both skip.

SAFETY: the agents test package is NOT covered by the mar conftest's DATABASE_URL redirect, so
both proofs build the cache against the THROWAWAY ``test_rca_cache`` (created + migrated to head
here), never the live ``rca_mar``.

Isolation note: the DB name ``test_rca_cache`` is intentionally DISTINCT from the mar conftest's
``test_rca_mar`` so running the mar suite and this suite in the same pytest session cannot cause
cross-suite DROP interference.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
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

_PROMPT = """---
name: xproc_echo
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 200
variables: [marker, value]
output_schema:
  type: object
  properties:
    seen: {type: string}
---
xproc echo prompt {{ marker }} value={{ value }}
"""
_SCRIPTED_CONTENT = '{"seen": "xproc-ok"}'


def _with_db_path(url: str, db_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


@pytest.fixture(scope="module")
def test_db_url() -> Generator[str, None, None]:
    """Create + migrate a throwaway ``test_rca_cache`` to head; yield its URL; DROP on teardown.

    Live ``rca_mar`` is never altered (admin ops touch the maintenance ``postgres`` DB).
    """
    from rca_mar.config import database_url

    live_url = database_url()
    admin_url = _with_db_path(live_url, "postgres")
    db_url = _with_db_path(live_url, TEST_DB_NAME)

    async def _recreate() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
                await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME} TEMPLATE template0"))
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


def _registry():
    from rca_llm import PromptRegistry, parse_prompt

    reg = PromptRegistry()
    reg.add(parse_prompt(_PROMPT))
    return reg


async def test_xprocess_determinism_two_instances(test_db_url: str) -> None:
    """RUNNABLE cross-instance proof: record on instance A, replay on a FRESH instance B over an
    independent engine — byte-identical content/structured, no upstream call on B."""
    from rca_llm import LLMClientImpl, NoUpstreamTransport
    from rca_llm.cache_pg import PostgresResponseCache
    from rca_llm.testing import ScriptedCompletionTransport
    from rca_mar.config import make_engine, make_session_factory

    variables = {"marker": "M", "value": "V"}

    # --- instance A: record ---
    cache_a = PostgresResponseCache(
        session_factory=make_session_factory(make_engine(test_db_url)))
    rec = LLMClientImpl(
        registry=_registry(),
        transport=ScriptedCompletionTransport({"xproc echo prompt": _SCRIPTED_CONTENT}),
        cache=cache_a)
    first = await rec.complete("xproc_echo", "v1", variables, correlation_id="xproc")
    assert first.cached is False
    assert first.structured == {"seen": "xproc-ok"}

    # --- instance B: fresh engine, replay-only transport, replay_from_cache=True ---
    cache_b = PostgresResponseCache(
        session_factory=make_session_factory(make_engine(test_db_url)))
    replay = LLMClientImpl(registry=_registry(), transport=NoUpstreamTransport(), cache=cache_b)
    second = await replay.complete(
        "xproc_echo", "v1", variables, correlation_id="xproc", replay_from_cache=True)

    assert second.cached is True
    assert second.content == first.content          # byte-identical
    assert second.structured == first.structured
    assert second.prompt_hash == first.prompt_hash


_RECORD_SCRIPT = '''
import asyncio, os
from rca_llm import LLMClientImpl
from rca_llm.cache_pg import PostgresResponseCache
from rca_llm.testing import ScriptedCompletionTransport
from rca_llm import PromptRegistry, parse_prompt
from rca_mar.config import make_engine, make_session_factory

PROMPT = {prompt!r}
URL = os.environ["XPROC_DB_URL"]

async def main():
    reg = PromptRegistry(); reg.add(parse_prompt(PROMPT))
    cache = PostgresResponseCache(session_factory=make_session_factory(make_engine(URL)))
    client = LLMClientImpl(registry=reg,
        transport=ScriptedCompletionTransport({{"xproc echo prompt": {content!r}}}), cache=cache)
    r = await client.complete("xproc_echo", "v1", {{"marker": "M", "value": "SUBPROC"}},
                              correlation_id="xproc-sub")
    assert r.cached is False
    print(r.content)

asyncio.run(main())
'''

_REPLAY_SCRIPT = '''
import asyncio, os
from rca_llm import LLMClientImpl, NoUpstreamTransport
from rca_llm.cache_pg import PostgresResponseCache
from rca_llm import PromptRegistry, parse_prompt
from rca_mar.config import make_engine, make_session_factory

PROMPT = {prompt!r}
URL = os.environ["XPROC_DB_URL"]

async def main():
    reg = PromptRegistry(); reg.add(parse_prompt(PROMPT))
    cache = PostgresResponseCache(session_factory=make_session_factory(make_engine(URL)))
    client = LLMClientImpl(registry=reg, transport=NoUpstreamTransport(), cache=cache)
    r = await client.complete("xproc_echo", "v1", {{"marker": "M", "value": "SUBPROC"}},
                              correlation_id="xproc-sub", replay_from_cache=True)
    assert r.cached is True
    print(r.content)

asyncio.run(main())
'''


async def test_xprocess_determinism_subprocess(test_db_url: str) -> None:
    """TRUE two-process proof: process A records, a separate process B replays with no upstream.
    Each process builds its own PostgresResponseCache over the same throwaway DB. Uses a
    distinct prompt value (``SUBPROC``) so its prompt_hash differs from the two-instance test's
    — both share the module-scoped DB and must not collide on the cache key."""
    env = dict(os.environ, XPROC_DB_URL=test_db_url)
    record_src = textwrap.dedent(
        _RECORD_SCRIPT.format(prompt=_PROMPT, content=_SCRIPTED_CONTENT))
    replay_src = textwrap.dedent(_REPLAY_SCRIPT.format(prompt=_PROMPT))

    a = subprocess.run([sys.executable, "-c", record_src],
                       capture_output=True, text=True, env=env)
    assert a.returncode == 0, f"record process failed:\n{a.stderr}"
    b = subprocess.run([sys.executable, "-c", replay_src],
                       capture_output=True, text=True, env=env)
    assert b.returncode == 0, f"replay process failed:\n{b.stderr}"

    # byte-identical content across the two independent processes
    assert a.stdout.strip() == _SCRIPTED_CONTENT
    assert b.stdout.strip() == a.stdout.strip()
