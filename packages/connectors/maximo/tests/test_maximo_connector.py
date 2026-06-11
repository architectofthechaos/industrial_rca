"""Hermetic tests for the `work_order` entity MCP (Sprint 2b Track 3 Task 5).

Drives the FastAPI fake Maximo OSLC surface via an ASGI transport so no real server is
needed. Asserts the tool set is the three work_order.* tools (+ test_connection) with NO
maximo.* name, and that every response carries provenance.connection_id.
"""
from __future__ import annotations

import json

import httpx
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticAssetGateway, StaticConnectionRouter
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_work_order_mcp

from fake_maximo import build_fake_maximo

CANONICAL = "asset:refinery-gc:unit-101:p-101a"
PLANT = "refinery-gc"
LOC = "CRDU-P101A"
CONNECTION_ID = "refinery-gc.cmms.maximo-main"


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id=PLANT, category="cmms",
            connector_type="maximo", base_url="http://maximo-fake", extra_config={},
        ),
    ])


def _assets() -> StaticAssetGateway:
    return StaticAssetGateway(handles={(CANONICAL, "cmms"): LOC})


def _factory():
    app = build_fake_maximo()
    transport = httpx.ASGITransport(app=app)

    def _make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, base_url="http://maximo-fake")

    return _make


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


def _mcp():
    return make_work_order_mcp(
        router=_router(), assets=_assets(), http_client_factory=_factory()
    )


async def test_work_order_tool_set_has_no_maximo_prefix():
    async with Client(_mcp()) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "work_order.list_for_asset", "work_order.get", "work_order.list_recent",
        "test_connection",
    }
    assert not any(n.startswith("maximo.") for n in names)


async def test_work_order_list_for_asset_returns_workorders():
    async with Client(_mcp()) as client:
        res = await client.call_tool("work_order.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[WorkOrder])
    assert resp.error is None and resp.data is not None
    assert len(resp.data) >= 1
    assert all(w.source_system == "maximo" for w in resp.data)
    assert all(w.opened_at.tzinfo is not None for w in resp.data)   # local -> UTC
    assert {"WO-50012345", "WO-50012402"} <= {w.work_order_id for w in resp.data}
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_work_order_get_by_wonum_returns_that_workorder():
    async with Client(_mcp()) as client:
        res = await client.call_tool("work_order.get", {"request": {
            "work_order_id": "WO-50012345", "plant_id": PLANT,
        }})
        resp = _parse(res, WorkOrder)
    assert resp.error is None and resp.data is not None
    assert resp.data.work_order_id == "WO-50012345"
    assert resp.data.failure_code == "LEK"
    assert resp.data.source_system == "maximo"
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_work_order_get_unknown_is_not_found():
    async with Client(_mcp()) as client:
        res = await client.call_tool("work_order.get", {"request": {
            "work_order_id": "WO-DOES-NOT-EXIST", "plant_id": PLANT,
        }})
        resp = _parse(res, WorkOrder)
    assert resp.data is None
    assert resp.error.code == "not_found"


async def test_work_order_list_recent_sorted_and_limited():
    async with Client(_mcp()) as client:
        res = await client.call_tool("work_order.list_recent", {"request": {
            "plant_id": PLANT, "limit": 2,
        }})
        resp = _parse(res, list[WorkOrder])
    assert resp.error is None and resp.data is not None
    assert len(resp.data) == 2                                       # limit applied
    # newest first by reportdate: WO-50012402 (2026-03-30) then WO-50012345 (2026-03-28)
    assert [w.work_order_id for w in resp.data] == ["WO-50012402", "WO-50012345"]
    assert resp.data[0].opened_at >= resp.data[1].opened_at
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_work_order_list_for_asset_default_gateway_has_no_cmms_handle():
    """The factory default (CanonicalSlugAssetGateway) can't resolve a cmms location, so
    list_for_asset returns a clean not_found ToolError until MAR wiring supplies one."""
    mcp = make_work_order_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("work_order.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[WorkOrder])
    assert resp.data is None
    assert resp.error.code == "not_found"


async def test_work_order_no_active_connection_is_source_unavailable():
    """A request for a plant/category with no configured connection maps to
    source_unavailable (a fixable config state), NOT internal_error."""
    empty_router = StaticConnectionRouter([])   # no connections registered
    mcp = make_work_order_mcp(
        router=empty_router, assets=_assets(), http_client_factory=_factory(),
    )
    async with Client(mcp) as client:
        res = await client.call_tool("work_order.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[WorkOrder])
    assert resp.data is None
    assert resp.error.code == "source_unavailable"
    assert resp.error.code != "internal_error"
