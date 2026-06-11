"""Health-check tests for the tag / operator_log connectors (PI historian + event frames).

Both entity MCPs share the TagHealthProbe. base_url is per-request (entity MCPs route per
connection); the probe fails gracefully when no URL is available, and ``default_base_url``
feeds the configured upstream so GET /health (base_url=None) still probes.

Hermetic: the probe is driven directly against the fake PI ASGI app. Live (skip-if-down):
checks the probe against the PI simulator at localhost:8001.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from fastmcp import Client
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_connector_sdk.health import TestConnectionResponse

from rca_connector_pi.health import ClientFactory, TagHealthProbe, _default_factory
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp

from fake_pi import build_fake_pi

PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://127.0.0.1:8001")


def _build_down_fake() -> Any:
    def _down(request: Any) -> Response:
        return Response(status_code=503)
    return Starlette(routes=[Route("/{path:path}", _down)])


def _asgi_factory(app: Any) -> ClientFactory:
    def _make(base_url: str, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://pi-fake")
    return _make


# ---- hermetic probe tests ----

async def test_tag_health_success_path():
    """All sub-checks pass against the fake; version harvested from openapi.json."""
    probe = TagHealthProbe(_asgi_factory(build_fake_pi()), default_base_url="http://pi-fake")
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:points", "schema:historian"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert checks[3].status == "pass"
    assert version == "2.99.0"


async def test_tag_health_no_base_url_fails_gracefully():
    probe = TagHealthProbe(_default_factory)   # no default_base_url
    checks, version = await probe.run(None, 5.0)
    assert len(checks) == 1
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert "no base_url configured" in (checks[0].message or "")
    assert version is None


async def test_tag_health_failure_path_gate_down():
    probe = TagHealthProbe(_asgi_factory(_build_down_fake()), default_base_url="http://pi-fake")
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


# ---- test_connection tool via MCP (registered on both servers) ----

def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id="refinery-gc.historian.pi-main", plant_id="refinery-gc",
            category="historian", connector_type="pi_historian",
            base_url="http://pi-fake", extra_config={},
        ),
    ])


async def test_tag_test_connection_registered_and_fails_without_url():
    """test_connection is registered; with no default_base_url it reports success=False."""
    mcp = make_tag_mcp(router=_router())   # no default_base_url
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "test_connection" in tools
        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is False
        assert resp.checks[0].name == "reachability"
        assert resp.checks[0].status == "fail"


async def test_operator_log_test_connection_registered():
    mcp = make_operator_log_mcp(router=_router())
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "test_connection" in tools


# ---- live variant (skip if PI sim is down) ----

def _pi_sim_reachable() -> bool:
    try:
        return httpx.get(f"{PI_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _pi_sim_reachable(),
    reason=f"PI simulator not reachable at {PI_SIM_URL}",
)
async def test_tag_health_live_against_simulator():
    probe = TagHealthProbe(_default_factory, default_base_url=PI_SIM_URL)
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:points", "schema:historian"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"   # schema:points
    assert checks[3].status == "pass"   # schema:historian
    assert version is not None
