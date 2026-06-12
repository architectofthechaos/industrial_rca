"""Host isolation + /health (Sprint 5 WI3 / D9, Risk #5).

The single-process multi-mount host trades process isolation for simplicity; D9 requires that
(a) one failing tool does not take the host down, and (b) a /health endpoint reports host +
per-mount status. Hermetic — uses an in-memory MAR + InMemoryAssetGraph + static router.
"""
from __future__ import annotations

import httpx
import pytest
from fastmcp import Client, FastMCP

from rca_agents.host import _static_dev_router, build_entity_host
from rca_kg.assets import InMemoryAssetGraph
from rca_mar.repository import InMemoryRepository


async def _host():
    return await build_entity_host(router=_static_dev_router(), mar_repo=InMemoryRepository(),
                                   asset_graph=InMemoryAssetGraph())


@pytest.mark.asyncio
async def test_failing_tool_does_not_crash_the_host():
    host = FastMCP("iso-test")

    @host.tool(name="boom")
    async def boom(request: dict):
        raise RuntimeError("kaboom")

    @host.tool(name="still_ok")
    async def still_ok(request: dict):
        return {"ok": True}

    async with Client(host) as client:
        # the failing tool surfaces as an error to the caller (not a host crash)
        with pytest.raises(Exception):
            await client.call_tool("boom", {"request": {}})
        # ...and the host stays up: another tool works on the same live session
        res = await client.call_tool("still_ok", {"request": {}})
        payload = res.structured_content if res.structured_content is not None else res.data
        assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_health_endpoint_reports_all_mounts_ready():
    host = await _host()
    app = host.http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://hosttest") as client:
            r = await client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    # every expected entity mount loaded its tools
    assert set(body["mounts"]) == {"asset", "kg", "tag", "operator_log", "work_order", "document"}
    assert all(body["mounts"].values()), body
    assert body["tool_count"] >= 10
