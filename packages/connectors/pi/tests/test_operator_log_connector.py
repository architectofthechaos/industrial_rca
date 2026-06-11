"""Hermetic tests for the `operator_log` entity MCP (Sprint 2b Track 3 Task 4)."""
from __future__ import annotations

import json

import httpx
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_contracts import Alarm, ToolResponse

from rca_connector_pi.server import make_operator_log_mcp

from fake_pi import build_fake_pi

CANONICAL = "asset:refinery-gc:unit-101:p-101a"
CONNECTION_ID = "refinery-gc.operator_log.pi-main"


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id="refinery-gc", category="operator_log",
            connector_type="pi_event_frames", base_url="http://pi-fake", extra_config={},
        ),
    ])


def _factory():
    app = build_fake_pi()
    transport = httpx.ASGITransport(app=app)

    def _make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, base_url="http://pi-fake")

    return _make


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


async def test_operator_log_tool_set_has_no_pi_prefix():
    mcp = make_operator_log_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {"operator_log.list_for_asset", "operator_log.get", "test_connection"}
    assert not any(n.startswith("pi.") for n in names)


async def test_operator_log_list_for_asset_filters_to_this_asset():
    mcp = make_operator_log_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("operator_log.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
            "start": "2026-03-01T00:00:00Z", "end": "2026-03-31T23:59:59Z",
        }})
        resp = _parse(res, list[Alarm])
    assert resp.error is None and resp.data is not None
    # only P-101A.* frames belong; the P-103A frame is filtered out
    assert len(resp.data) >= 1
    assert all(a.tag_name is not None and a.tag_name.startswith("P-101A.") for a in resp.data)
    assert resp.data[0].source_system == "pi_event_frames"
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_operator_log_get_returns_one_alarm():
    mcp = make_operator_log_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("operator_log.get", {"request": {
            "canonical_id": CANONICAL, "log_id": "ALM-2026-03-13-9912",
        }})
        resp = _parse(res, Alarm)
    assert resp.error is None and resp.data is not None
    assert resp.data.message == "ALM-2026-03-13-9912"
    assert resp.data.tag_name == "P-101A.vibration_radial"
    assert resp.data.priority == 3  # warning
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_operator_log_get_unknown_is_not_found():
    mcp = make_operator_log_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("operator_log.get", {"request": {
            "canonical_id": CANONICAL, "log_id": "ALM-DOES-NOT-EXIST",
        }})
        resp = _parse(res, Alarm)
    assert resp.data is None
    assert resp.error.code == "not_found"
