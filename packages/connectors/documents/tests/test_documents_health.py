"""Health-check tests for the Documents connector (Sprint 2a Task 10).

Hermetic: drives a tiny FastAPI fake mimicking /openapi.json and /search.

Live (skip-if-down): checks the probe against the Documents simulator at localhost:8003.
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

from rca_connector_documents.health import ClientFactory, DocumentsHealthProbe, _default_factory
from rca_connector_documents.server import make_documents_mcp
from rca_connector_sdk.health import TestConnectionResponse

DOCS_SIM_URL = os.environ.get("DOCS_SIM_URL", "http://127.0.0.1:8003")

# ---- fake upstream ----


def _build_docs_health_fake() -> FastAPI:
    app = FastAPI(title="Fake Docs", version="1.0.0")

    @app.get("/search")
    def search(q: str = "", top: int = 5) -> dict[str, Any]:
        return {"value": []}

    return app


def _build_down_fake() -> Any:
    def _down(request: Any) -> Response:
        return Response(status_code=503)
    return Starlette(routes=[Route("/{path:path}", _down)])


def _asgi_factory(app: Any) -> ClientFactory:
    def _make(base_url_override: str | None, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://docs-fake")
    return _make


# ---- hermetic tests ----

async def test_documents_health_success_path():
    probe = DocumentsHealthProbe(_asgi_factory(_build_docs_health_fake()))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:search"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert version == "1.0.0"


async def test_documents_health_failure_path_gate_down():
    probe = DocumentsHealthProbe(_asgi_factory(_build_down_fake()))
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


async def test_documents_test_connection_tool_via_mcp():
    app = _build_docs_health_fake()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://docs-fake") as http:
        mcp = make_documents_mcp(http_client=http, health_client_factory=_asgi_factory(app))
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert {"documents.search", "documents.fetch", "test_connection"} <= tools

            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is True
            assert [c.name for c in resp.checks] == ["reachability", "auth", "schema:search"]


async def test_documents_test_connection_failure_returns_success_false():
    down_app = _build_down_fake()
    transport = httpx.ASGITransport(app=down_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://docs-fake") as http:
        mcp = make_documents_mcp(http_client=http, health_client_factory=_asgi_factory(down_app))
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
        return httpx.get(f"{DOCS_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Documents simulator not reachable at {DOCS_SIM_URL}",
)
async def test_documents_health_live_against_simulator():
    probe = DocumentsHealthProbe(_default_factory(DOCS_SIM_URL))
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:search"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
