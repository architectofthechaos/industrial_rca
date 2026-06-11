"""Health-check tests for the Maximo connector (Sprint 2a Task 10).

Hermetic: drives a tiny FastAPI fake mimicking the Maximo OSLC openapi.json and
/maxrest/oslc/os/mxwo routes.

Live (skip-if-down): checks the probe against the Maximo simulator at localhost:8002.
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

from rca_connector_maximo.health import ClientFactory, MaximoHealthProbe, _default_factory
from rca_connector_maximo.server import make_maximo_mcp
from rca_connector_sdk.health import TestConnectionResponse

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")

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
    def _make(base_url_override: str | None, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://maximo-fake")
    return _make


# ---- hermetic tests ----

async def test_maximo_health_success_path():
    probe = MaximoHealthProbe(_asgi_factory(_build_maximo_health_fake()))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:workorders"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert version == "7.6.1"


async def test_maximo_health_failure_path_gate_down():
    probe = MaximoHealthProbe(_asgi_factory(_build_down_fake()))
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


async def test_maximo_test_connection_tool_via_mcp():
    app = _build_maximo_health_fake()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://maximo-fake") as http:
        mcp = make_maximo_mcp(http_client=http, health_client_factory=_asgi_factory(app))
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert {"maximo.get_workorders", "maximo.get_failure_history",
                    "maximo.preview_writeback", "maximo.commit_writeback",
                    "test_connection"} <= tools

            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is True
            assert [c.name for c in resp.checks] == [
                "reachability", "auth", "schema:workorders"
            ]


async def test_maximo_test_connection_failure_returns_success_false():
    down_app = _build_down_fake()
    transport = httpx.ASGITransport(app=down_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://maximo-fake") as http:
        mcp = make_maximo_mcp(http_client=http, health_client_factory=_asgi_factory(down_app))
        async with Client(mcp) as client:
            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is False
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
async def test_maximo_health_live_against_simulator():
    probe = MaximoHealthProbe(_default_factory(MAXIMO_SIM_URL))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:workorders"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
    assert version is not None
