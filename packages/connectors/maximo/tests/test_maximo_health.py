"""Health-check tests for the work_order connector (Maximo-backed, Sprint 2b Track 3).

The work_order MCP routes per-request, so the probe takes a per-request base_url with a
configured default_base_url fallback (the pi TagHealthProbe shape). Sub-checks unchanged:
reachability / auth-skip / schema:workorders.

Hermetic: drives a tiny FastAPI fake. Live (skip-if-down): checks the probe against the
Maximo simulator at localhost:8002.
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

from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_connector_sdk.health import TestConnectionResponse

from rca_connector_maximo.health import ClientFactory, WorkOrderHealthProbe, _default_factory
from rca_connector_maximo.server import make_work_order_mcp

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
PLANT = "refinery-gc"

# ---- fake upstream ----


def _build_maximo_health_fake() -> FastAPI:
    app = FastAPI(title="Maximo OSLC Simulator", version="7.6.1")

    @app.get("/maxrest/oslc/os/mxwo")
    def mxwo(pageSize: int | None = None) -> dict[str, Any]:
        return {"member": [], "responseInfo": {"totalCount": 0}}

    return app


def _build_down_fake() -> Any:
    def _down(request: Any) -> Response:
        return Response(status_code=503)
    return Starlette(routes=[Route("/{path:path}", _down)])


def _asgi_factory(app: Any) -> ClientFactory:
    def _make(base_url: str, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://maximo-fake")
    return _make


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id="refinery-gc.cmms.maximo-main", plant_id=PLANT, category="cmms",
            connector_type="maximo", base_url="http://maximo-fake", extra_config={},
        ),
    ])


# ---- hermetic probe tests ----

async def test_work_order_health_success_path():
    probe = WorkOrderHealthProbe(
        _asgi_factory(_build_maximo_health_fake()), default_base_url="http://maximo-fake"
    )
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:workorders"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert version == "7.6.1"


async def test_work_order_health_no_base_url_fails_gracefully():
    probe = WorkOrderHealthProbe(_default_factory)   # no default_base_url
    checks, version = await probe.run(None, 5.0)
    assert len(checks) == 1
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert "no base_url configured" in (checks[0].message or "")
    assert version is None


async def test_work_order_health_failure_path_gate_down():
    probe = WorkOrderHealthProbe(
        _asgi_factory(_build_down_fake()), default_base_url="http://maximo-fake"
    )
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


# ---- test_connection tool via MCP ----

async def test_work_order_test_connection_registered_and_fails_without_url():
    """test_connection is registered; with no default_base_url it reports success=False
    (the entity MCP routes per request, so the probe has no URL on a base GET /health)."""
    mcp = make_work_order_mcp(router=_router())   # no default_base_url
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "test_connection" in tools
        assert not any(n.startswith("maximo.") for n in tools)
        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is False
        assert resp.checks[0].name == "reachability"
        assert resp.checks[0].status == "fail"


# ---- live variant ----

def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{MAXIMO_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Maximo simulator not reachable at {MAXIMO_SIM_URL}",
)
async def test_work_order_health_live_against_simulator():
    probe = WorkOrderHealthProbe(_default_factory, default_base_url=MAXIMO_SIM_URL)
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:workorders"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
    assert version is not None
