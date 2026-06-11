"""Health-check tests for the asset_hierarchy connector (Sprint 2a Task 10).

The asset_hierarchy connector has no globally configured upstream — base_url is
per-request.  The probe fails gracefully when no URL is available.

Hermetic: reuses the existing fake_af.py FastAPI app (which exposes /assetdatabases
and matches PI AF shape).  FastAPI auto-generates /openapi.json from its title/version.

Live (skip-if-down): checks the probe against the PI simulator at localhost:8001
(same AF backend that the pi connector uses).
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

from rca_connector_asset_hierarchy.health import (
    AssetHierarchyHealthProbe,
    ClientFactory,
    _default_factory,
)
from rca_connector_asset_hierarchy.server import make_asset_hierarchy_mcp
from rca_connector_sdk.health import TestConnectionResponse

PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://127.0.0.1:8001")

# ---- fake upstream ----


def _build_af_health_fake() -> Any:
    """Minimal fake: FastAPI's auto /openapi.json + /assetdatabases from fake_af."""
    from fake_af import make_fake_af_app  # pytest adds tests/ dir to sys.path
    # make_fake_af_app returns a FastAPI app titled "Fake PI AF" with version "0.1.0"
    # FastAPI auto-generates /openapi.json with info.version from the app version.
    # We wrap it in a new FastAPI with a known version for version assertions.
    base = make_fake_af_app()
    # Inject a version by wrapping the app; simpler: just use the base app and don't
    # assert a specific version (assert version is not None instead).
    return base


def _build_versioned_af_fake() -> Any:
    """FastAPI fake with known version "1.2.3" for version harvesting assertion.

    Note: return-type annotations on route handlers are omitted to avoid Pydantic
    forward-ref resolution issues when ``from __future__ import annotations`` is active.
    """
    from fastapi import FastAPI

    app = FastAPI(title="Fake PI AF", version="1.2.3")

    @app.get("/assetdatabases")
    def assetdatabases():  # no return annotation — avoids pydantic forward-ref issue
        return {"Items": [{"WebId": "W1", "Name": "Refinery-GC", "Path": "\\\\PI\\Refinery-GC"}]}

    return app


def _build_down_fake() -> Any:
    def _down(request: Any) -> Response:
        return Response(status_code=503)
    return Starlette(routes=[Route("/{path:path}", _down)])


def _asgi_factory(app: Any) -> ClientFactory:
    """ClientFactory backed by the given ASGI app."""
    def _make(base_url: str, timeout: float) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://af-fake")
    return _make


# ---- hermetic tests ----

async def test_asset_hierarchy_health_success_path():
    app = _build_versioned_af_fake()
    probe = AssetHierarchyHealthProbe(_asgi_factory(app), default_base_url="http://af-fake")
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:assetdatabases"]
    assert checks[0].status == "pass"
    assert checks[1].status == "skip"
    assert checks[2].status == "pass"
    assert version == "1.2.3"


async def test_asset_hierarchy_health_no_base_url_fails_gracefully():
    """When no base_url is available (not in request, not as default) probe returns
    a single fail check with an informative message — no timeout spent."""
    probe = AssetHierarchyHealthProbe(_default_factory)   # no default_base_url
    checks, version = await probe.run(None, 5.0)
    assert len(checks) == 1
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert "no base_url configured" in (checks[0].message or "")
    assert version is None


async def test_asset_hierarchy_health_failure_path_gate_down():
    probe = AssetHierarchyHealthProbe(
        _asgi_factory(_build_down_fake()),
        default_base_url="http://af-fake",
    )
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "reachability"
    assert checks[0].status == "fail"
    assert all(c.status == "skip" for c in checks[1:])
    assert version is None


async def test_asset_hierarchy_test_connection_tool_via_mcp():
    """test_connection tool is registered; tool list includes it alongside crawl tools."""
    app = _build_versioned_af_fake()

    def crawl_factory(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://af-fake"
        )

    mcp = make_asset_hierarchy_mcp(
        http_client_factory=crawl_factory,
        default_base_url="http://af-fake",
    )
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert {"asset_hierarchy.crawl", "asset_hierarchy.crawl_subtree",
                "test_connection"} <= tools


async def test_asset_hierarchy_test_connection_with_explicit_base_url():
    """Probe with explicit base_url override passes all checks against the ASGI fake."""
    app = _build_versioned_af_fake()
    probe = AssetHierarchyHealthProbe(_asgi_factory(app), default_base_url="http://af-fake")
    checks, version = await probe.run("http://af-fake", 5.0)
    assert [c.name for c in checks] == ["reachability", "auth", "schema:assetdatabases"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
    assert version == "1.2.3"


async def test_asset_hierarchy_test_connection_no_url_returns_success_false():
    """test_connection with no base_url and no default → success=False."""
    mcp = make_asset_hierarchy_mcp()   # no default_base_url
    async with Client(mcp) as client:
        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is False
        assert resp.checks[0].name == "reachability"
        assert resp.checks[0].status == "fail"


# ---- live variant ----

def _pi_sim_reachable() -> bool:
    try:
        return httpx.get(f"{PI_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _pi_sim_reachable(),
    reason=f"PI simulator not reachable at {PI_SIM_URL}",
)
async def test_asset_hierarchy_health_live_against_pi_simulator():
    """Live probe against the PI/AF simulator (port 8001)."""
    probe = AssetHierarchyHealthProbe(_default_factory)
    checks, version = await probe.run(PI_SIM_URL, 5.0)
    names = [c.name for c in checks]
    assert names == ["reachability", "auth", "schema:assetdatabases"]
    assert checks[0].status == "pass"
    assert checks[2].status == "pass"
