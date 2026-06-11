"""Health-check tests for the PI connector (Sprint 2a Task 10).

Hermetic: drives a tiny FastAPI fake that mimics the PI Web API's openapi.json,
/assetdatabases, and /eventframes routes so no real server is needed.

Live (skip-if-down): checks the probe against the real PI simulator at localhost:8001.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastmcp import Client
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from rca_connector_pi.health import ClientFactory, PiHealthProbe, _default_factory
from rca_connector_pi.server import make_pi_mcp
from rca_connector_sdk.health import TestConnectionResponse

PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://127.0.0.1:8001")

# ---- fake upstream ----


def _build_pi_health_fake() -> FastAPI:
    """Minimal fake for health probes; version "2.99.0" in FastAPI title."""
    app = FastAPI(title="Fake PI", version="2.99.0")

    @app.get("/assetdatabases")
    def assetdatabases() -> dict[str, Any]:
        return {"Items": [{"Name": "Refinery-GC"}]}

    @app.get("/eventframes")
    def eventframes(startTime: str = "", endTime: str = "") -> dict[str, Any]:
        return {"Items": []}

    return app


def _build_down_fake() -> Any:
    """Starlette app that returns 503 for every request (simulates unreachable upstream)."""
    def _down(request: Any) -> Response:
        return Response(status_code=503)
    return Starlette(routes=[Route("/{path:path}", _down)])


def _asgi_factory(app: Any) -> ClientFactory:
    """Return a ClientFactory backed by the given ASGI app."""
    def _make(base_url_override: str | None, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://pi-fake")
    return _make


# ---- hermetic tests ----

async def test_pi_health_success_path():
    """All sub-checks pass against the fake; version is harvested from openapi.json."""
    probe = PiHealthProbe(_asgi_factory(_build_pi_health_fake()))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:af", "schema:historian"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert checks[3].status == "pass"
    assert version == "2.99.0"


async def test_pi_health_failure_path_gate_down():
    """When reachability fails all subsequent checks are skipped."""
    probe = PiHealthProbe(_asgi_factory(_build_down_fake()))
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


async def test_pi_test_connection_tool_via_mcp():
    """test_connection tool present + returns success=True with the fake upstream."""
    app = _build_pi_health_fake()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pi-fake") as http:
        mcp = make_pi_mcp(http_client=http, health_client_factory=_asgi_factory(app))
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert {"pi.get_series", "pi.get_summary", "pi.get_event_frames",
                    "test_connection"} <= tools

            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is True
            assert [c.name for c in resp.checks] == [
                "reachability", "auth", "schema:af", "schema:historian"
            ]
            assert resp.upstream_version == "2.99.0"


async def test_pi_test_connection_failure_returns_success_false():
    """test_connection returns success=False when upstream is down."""
    down_app = _build_down_fake()
    transport = httpx.ASGITransport(app=down_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pi-fake") as http:
        mcp = make_pi_mcp(http_client=http, health_client_factory=_asgi_factory(down_app))
        async with Client(mcp) as client:
            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is False
            assert resp.checks[0].name == "reachability"
            assert resp.checks[0].status == "fail"


async def test_pi_health_route_200():
    """GET /health returns 200 healthy when the fake is up."""
    app = _build_pi_health_fake()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://pi-fake") as http:
        mcp = make_pi_mcp(http_client=http, health_client_factory=_asgi_factory(app))
    health_transport = httpx.ASGITransport(app=mcp.http_app())
    async with httpx.AsyncClient(transport=health_transport, base_url="http://pi") as hclient:
        resp = await hclient.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


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
async def test_pi_health_live_against_simulator():
    """Live probe against the PI simulator; all checks pass."""
    probe = PiHealthProbe(_default_factory(PI_SIM_URL))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:af", "schema:historian"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"    # schema:af
    assert checks[3].status == "pass"    # schema:historian
    assert version is not None
