"""Health-check tests for the document connector (SharePoint-sim-backed, Sprint 2b Track 3).

The document MCP routes per-request, so the probe takes a per-request base_url with a
configured default_base_url fallback (the pi TagHealthProbe shape). Sub-checks unchanged:
reachability / auth-skip / schema:search.

Hermetic: drives a tiny FastAPI fake. Live (skip-if-down): checks the probe against the
Documents simulator at localhost:8004.
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

from rca_connector_documents.health import (
    ClientFactory,
    DocumentHealthProbe,
    _default_factory,
)
from rca_connector_documents.server import make_document_mcp

DOCS_SIM_URL = os.environ.get("DOCS_SIM_URL", "http://127.0.0.1:8004")
PLANT = "refinery-gc"

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
    def _make(base_url: str, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://docs-fake")
    return _make


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id="refinery-gc.document.sharepoint-main", plant_id=PLANT,
            category="document", connector_type="sharepoint",
            base_url="http://docs-fake", extra_config={},
        ),
    ])


# ---- hermetic probe tests ----

async def test_document_health_success_path():
    probe = DocumentHealthProbe(
        _asgi_factory(_build_docs_health_fake()), default_base_url="http://docs-fake"
    )
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:search"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert version == "1.0.0"


async def test_document_health_no_base_url_fails_gracefully():
    probe = DocumentHealthProbe(_default_factory)   # no default_base_url
    checks, version = await probe.run(None, 5.0)
    assert len(checks) == 1
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert "no base_url configured" in (checks[0].message or "")
    assert version is None


async def test_document_health_failure_path_gate_down():
    probe = DocumentHealthProbe(
        _asgi_factory(_build_down_fake()), default_base_url="http://docs-fake"
    )
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


# ---- test_connection tool via MCP ----

async def test_document_test_connection_registered_and_fails_without_url():
    mcp = make_document_mcp(router=_router())   # no default_base_url
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "test_connection" in tools
        assert not any(n.startswith("documents.") for n in tools)
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
        return httpx.get(f"{DOCS_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Documents simulator not reachable at {DOCS_SIM_URL}",
)
async def test_document_health_live_against_simulator():
    probe = DocumentHealthProbe(_default_factory, default_base_url=DOCS_SIM_URL)
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:search"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
