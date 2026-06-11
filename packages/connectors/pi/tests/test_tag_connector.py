"""Hermetic tests for the `tag` entity MCP (Sprint 2b Track 3 Task 4).

Drives the FastAPI fake PI Web API via an ASGI transport so no real server is needed.
Asserts the tool set is the four tag.* tools (+ test_connection) with NO pi.* name, and
that every response carries provenance.connection_id.
"""
from __future__ import annotations

import json

import httpx
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_contracts import Measurement, MeasurementSeries, TagDescriptor, ToolResponse

from rca_connector_pi.models import TagInfo
from rca_connector_pi.server import make_tag_mcp

from fake_pi import build_fake_pi

CANONICAL = "asset:refinery-gc:unit-101:p-101a"
CONNECTION_ID = "refinery-gc.historian.pi-main"


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id="refinery-gc", category="historian",
            connector_type="pi_historian", base_url="http://pi-fake", extra_config={},
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


async def test_tag_tool_set_has_no_pi_prefix():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "tag.get_history", "tag.get_current", "tag.list_for_asset",
        "tag.get_metadata", "test_connection",
    }
    assert not any(n.startswith("pi.") for n in names)


async def test_tag_list_for_asset_returns_tags():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.list_for_asset", {"request": {
            "canonical_id": CANONICAL,
        }})
        resp = _parse(res, list[TagInfo])
    assert resp.error is None and resp.data is not None
    assert len(resp.data) >= 1
    names = {t.tag_name for t in resp.data}
    assert "P-101A.discharge_pressure" in names
    disch = next(t for t in resp.data if t.tag_name == "P-101A.discharge_pressure")
    assert disch.role == "discharge_pressure"
    assert disch.engineering_units == "psig"
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_tag_get_history_normalizes_and_carries_connection_id():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_history", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.discharge_pressure",
            "mode": "stored",
            "start": "2026-03-06T00:00:00Z", "end": "2026-03-06T01:00:00Z",
        }})
        resp = _parse(res, MeasurementSeries)
    assert resp.error is None and resp.data is not None
    assert resp.data.tag.canonical_id == CANONICAL
    assert resp.data.tag.tag_name == "P-101A.discharge_pressure"
    assert len(resp.data.values) == 2
    # psig -> kPa scale (gauge magnitude): 14.5 * 6_894.757293168
    assert resp.data.values[0].value == 14.5 * 6_894.757293168
    assert resp.data.values[0].timestamp.tzinfo is not None
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_tag_get_history_interpolated_carries_flag():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_history", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.discharge_pressure",
            "mode": "interpolated",
            "start": "2026-03-06T00:00:00Z", "end": "2026-03-06T01:00:00Z",
        }})
        resp = _parse(res, MeasurementSeries)
    assert resp.error is None
    assert resp.data.mode.value == "interpolated"
    assert all(m.is_interpolated for m in resp.data.values)


async def test_tag_get_current_returns_measurement():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_current", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.discharge_pressure",
        }})
        resp = _parse(res, Measurement)
    assert resp.error is None and resp.data is not None
    assert resp.data.value == 14.9 * 6_894.757293168
    assert resp.data.timestamp.tzinfo is not None
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_tag_get_metadata_returns_descriptor_with_units():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_metadata", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.discharge_pressure",
        }})
        resp = _parse(res, TagDescriptor)
    assert resp.error is None and resp.data is not None
    assert resp.data.canonical_id == CANONICAL
    assert resp.data.tag_name == "P-101A.discharge_pressure"
    assert resp.data.role == "discharge_pressure"
    assert resp.data.source_unit == "psig"
    assert resp.data.qudt_unit == "kPa"
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_tag_get_history_unknown_tag_is_not_found():
    mcp = make_tag_mcp(router=_router(), http_client_factory=_factory())
    async with Client(mcp) as client:
        res = await client.call_tool("tag.get_history", {"request": {
            "canonical_id": CANONICAL, "tag_name": "P-101A.does_not_exist",
            "mode": "stored",
            "start": "2026-03-06T00:00:00Z", "end": "2026-03-06T01:00:00Z",
        }})
        resp = _parse(res, MeasurementSeries)
    assert resp.data is None
    assert resp.error.code == "not_found"
