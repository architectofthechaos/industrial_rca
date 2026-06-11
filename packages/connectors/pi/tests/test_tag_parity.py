"""Live parity test: the `tag` MCP against the REAL EPIC-002 PI simulator (:8001).

Talks to the simulator over HTTP — the product test venv never imports rca_simulator.
Skips cleanly when the sim isn't running. Run it with: `task parity:pi`.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_contracts import MeasurementSeries, ToolResponse

from rca_connector_pi.models import TagInfo
from rca_connector_pi.server import make_tag_mcp

PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://127.0.0.1:8001")
CANONICAL = "asset:refinery-gc:unit-101:p-101a"
CONNECTION_ID = "refinery-gc.historian.pi-main"


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{PI_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"PI simulator not reachable at {PI_SIM_URL} (run `task parity:pi`)",
)


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id="refinery-gc", category="historian",
            connector_type="pi_historian", base_url=PI_SIM_URL, extra_config={},
        ),
    ])


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


async def test_tag_list_for_asset_p101a_has_six_tags_against_real_sim():
    mcp = make_tag_mcp(router=_router())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[TagInfo])
    assert resp.error is None, resp.error
    assert resp.data is not None
    assert len(resp.data) == 6
    assert {t.tag_name for t in resp.data} >= {"P-101A.discharge_pressure"}
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_tag_get_history_discharge_pressure_non_empty_against_real_sim():
    mcp = make_tag_mcp(router=_router())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_history", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.discharge_pressure",
            "mode": "stored",
            "start": "2026-03-06T00:00:00Z", "end": "2026-03-06T00:05:00Z",
        }})
        resp = _parse(res, MeasurementSeries)
    assert resp.error is None, resp.error
    assert resp.data is not None and len(resp.data.values) > 0
    assert resp.data.tag.canonical_id == CANONICAL
    assert resp.data.values[0].timestamp.tzinfo is not None
    assert resp.provenance.record_count == len(resp.data.values)
    assert resp.provenance.connection_id == CONNECTION_ID
