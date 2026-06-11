"""S13.1 DoD: the echo connector against the echo source, end-to-end through MCP.

Uses only the SDK + contracts. Success returns a validated ToolResponse with
provenance and SI-normalized values; a source 5xx returns a ToolError (no data).
"""
import json
from uuid import uuid4

import httpx
from fastmcp import Client
from rca_contracts import MeasurementSeries, TagDescriptor, ToolResponse

from rca_connector_echo.echo_source import build_echo_source
from rca_connector_echo.server import make_echo_mcp

SID = uuid4()
DOWN = uuid4()


def _signal(signal_id) -> TagDescriptor:
    return TagDescriptor(
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        tag_name=str(signal_id),
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
    )


def _parse(result) -> "ToolResponse[MeasurementSeries]":
    # FastMCP returns JSON-native structured content; a real MCP client parses JSON,
    # so reconstruct via model_validate_json (strict mode accepts JSON str->UUID/datetime).
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[MeasurementSeries].model_validate_json(json.dumps(payload))


async def test_echo_connector_success_and_error_paths():
    source = build_echo_source(down_signal=str(DOWN))
    transport = httpx.ASGITransport(app=source)
    async with httpx.AsyncClient(transport=transport, base_url="http://echo") as http:
        mcp = make_echo_mcp(http_client=http, signals={SID: _signal(SID), DOWN: _signal(DOWN)})

        async with Client(mcp) as client:
            # tool is registered under its catalog name
            assert "echo.get_series" in {t.name for t in await client.list_tools()}

            # --- success ---
            ok = await client.call_tool(
                "echo.get_series", {"request": {"signal_id": str(SID), "mode": "stored"}}
            )
            resp = _parse(ok)
            assert resp.error is None and resp.data is not None
            assert len(resp.data.values) == 3
            assert resp.data.values[0].value == 100_000.0           # 1 bar -> Pa
            assert resp.data.values[0].timestamp.tzinfo is not None  # UTC-aware
            assert resp.provenance is not None
            assert resp.provenance.record_count == 3
            assert resp.provenance.tool_name == "echo.get_series"
            assert "discharge_pressure" in resp.provenance.raw_tags  # forensic only

            # --- error: source 503 -> ToolError, no data leaked ---
            bad = await client.call_tool(
                "echo.get_series", {"request": {"signal_id": str(DOWN)}}
            )
            err = _parse(bad)
            assert err.data is None and err.provenance is None
            assert err.error is not None and err.error.code == "source_unavailable"
