"""Live dynamic-routing proof (Sprint 5 WI4 / D10).

Against the running HTTP host (dynamic RegistryConnectionRouter) + the connections registry:
disabling a connection makes the NEXT tool call reroute (here: raise NoActiveConnection ->
source_unavailable) with NO host/worker restart — the static-snapshot limitation is gone. The
four resolution rules are covered hermetically in connector_sdk/tests/test_registry_router.py.

Stack-gated: needs `task probe:host` (dynamic router) + Postgres connections seeded. No LLM keys
required (a single tool call over MCP, no probe).
"""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RCA_STACK") != "1",
                                reason="requires the live HTTP host + connections registry")

CID = "asset:refinery-gc:unit-101:p-101a"
DOC_CONN = "refinery-gc.document.sharepoint-main"
HOST_URL = os.environ.get("MCP_HOST_URL", "http://127.0.0.1:8100/mcp")


async def _doc_search(client):
    res = await client.call_tool(
        "document.search_for_asset", {"request": {"canonical_id": CID, "query": "seal"}})
    sc = res.structured_content or {}
    err = sc.get("error")
    return ((err or {}).get("code") if err else None, len(sc.get("data") or []))


async def _set_status(repo, status: str):
    rows = await repo.list_connections(plant_id="refinery-gc", category="document")
    row = next(r for r in rows if r.connection_id == DOC_CONN)
    await repo.upsert_connection(replace(row, status=status))


@pytest.mark.asyncio
async def test_disable_reroutes_without_restart():
    from fastmcp import Client
    from rca_mar.config import make_engine, make_session_factory
    from rca_mar.repository_pg import PostgresRepository

    repo = PostgresRepository(make_session_factory(make_engine()))
    async with Client(HOST_URL) as client:   # ONE host session, never restarted across the asserts
        try:
            await _set_status(repo, "active")
            err, n = await _doc_search(client)
            assert err is None and n >= 1, f"active document conn should resolve: err={err} n={n}"

            await _set_status(repo, "disabled")
            err, n = await _doc_search(client)
            assert err == "source_unavailable" and n == 0, (
                f"disabled conn should reroute to NoActiveConnection without restart: err={err}")
        finally:
            await _set_status(repo, "active")   # restore
        err, n = await _doc_search(client)
        assert err is None and n >= 1, "re-enabling restores routing on the next call"
