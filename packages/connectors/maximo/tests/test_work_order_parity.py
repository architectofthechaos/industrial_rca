"""Live parity test: the `work_order` MCP against the REAL Maximo simulator (:8002).

Talks over HTTP (default http://127.0.0.1:8002); never imports rca_simulator. Skips when
the sim isn't running. Run with: `task parity:maximo`.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticAssetGateway, StaticConnectionRouter
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_work_order_mcp

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
CANONICAL = "asset:refinery-gc:unit-101:p-101a"
PLANT = "refinery-gc"
LOC = "CRDU-P101A"   # P-101A's maximo_location in the reference fixture
CONNECTION_ID = "refinery-gc.cmms.maximo-main"


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{MAXIMO_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Maximo simulator not reachable at {MAXIMO_SIM_URL} (run `task parity:maximo`)",
)


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id=PLANT, category="cmms",
            connector_type="maximo", base_url=MAXIMO_SIM_URL, extra_config={},
        ),
    ])


def _assets() -> StaticAssetGateway:
    return StaticAssetGateway(handles={(CANONICAL, "cmms"): LOC})


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


async def test_work_order_list_for_asset_against_real_simulator():
    mcp = make_work_order_mcp(router=_router(), assets=_assets())
    async with Client(mcp) as client:
        res = await client.call_tool("work_order.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[WorkOrder])
    assert resp.error is None, resp.error
    assert resp.data is not None and len(resp.data) > 0
    wonums = {w.work_order_id for w in resp.data}
    assert {"WO-50012345", "WO-50012402"} <= wonums          # seal-leak scenario WOs
    assert all(w.source_system == "maximo" for w in resp.data)
    assert all(w.opened_at.tzinfo is not None for w in resp.data)
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_work_order_get_and_list_recent_against_real_simulator():
    mcp = make_work_order_mcp(router=_router(), assets=_assets())
    async with Client(mcp) as client:
        one = _parse(await client.call_tool("work_order.get", {"request": {
            "work_order_id": "WO-50012402", "plant_id": PLANT,
        }}), WorkOrder)
        assert one.error is None and one.data.work_order_id == "WO-50012402"
        assert one.provenance.connection_id == CONNECTION_ID

        recent = _parse(await client.call_tool("work_order.list_recent", {"request": {
            "plant_id": PLANT, "limit": 5,
        }}), list[WorkOrder])
    assert recent.error is None and recent.data is not None
    assert len(recent.data) <= 5
    # newest-first ordering by reportdate
    opened = [w.opened_at for w in recent.data]
    assert opened == sorted(opened, reverse=True)
    assert recent.provenance.connection_id == CONNECTION_ID
