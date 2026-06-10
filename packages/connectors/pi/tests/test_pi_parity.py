"""S13.8 parity test: PI connector against the REAL EPIC-002 PI simulator.

Talks to the simulator over HTTP (default http://127.0.0.1:8001) — the product
test venv never imports or installs rca_simulator; they communicate exactly as the
connector will talk to a real PI server. Skips cleanly when the sim isn't running,
so plain `uv run pytest` stays green. Run it with: `task parity:pi`.
"""
import base64
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import MeasurementSeries, PressureReference, SignalDescriptor, ToolResponse

from rca_connector_pi.server import make_pi_mcp

PI_SIM_URL = os.environ.get("PI_SIM_URL", "http://127.0.0.1:8001")
SID = uuid4()


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{PI_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(), reason=f"PI simulator not reachable at {PI_SIM_URL} (run `task parity:pi`)"
)


def _webid(signal_key: str) -> str:
    # the sim's WebID scheme (replicated, not imported — keeps the sim out of this venv).
    raw = base64.urlsafe_b64encode(signal_key.encode()).decode().rstrip("=")
    return "S1" + raw


def _signal() -> SignalDescriptor:
    return SignalDescriptor(
        signal_id=SID, tenant_id=uuid4(), asset_id=uuid4(),
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.gauge,            # PI emits psig
    )


def _parse(result) -> "ToolResponse[MeasurementSeries]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[MeasurementSeries].model_validate_json(json.dumps(payload))


async def test_pi_get_series_against_real_simulator():
    signals = {SID: _signal()}
    bindings = {(SID, "pi"): SourceBinding(handle=_webid("P-101A.discharge_pressure"),
                                           raw_unit="psig")}
    async with httpx.AsyncClient(base_url=PI_SIM_URL) as http:
        mcp = make_pi_mcp(http_client=http, signals=signals, bindings=bindings)
        async with Client(mcp) as client:
            res = await client.call_tool("pi.get_series", {"request": {
                "signal_id": str(SID), "mode": "stored",
                "start": "2026-03-06T00:00:00Z", "end": "2026-03-06T00:05:00Z",
            }})
            resp = _parse(res)

            # the connector correctly consumed the REAL sim's wire format -> canonical output
            assert resp.error is None, resp.error
            assert resp.data is not None and len(resp.data.values) > 0
            assert resp.data.values[0].timestamp.tzinfo is not None         # UTC-aware
            assert all(isinstance(m.value, float) for m in resp.data.values)  # psig -> Pa
            assert resp.provenance is not None
            assert resp.provenance.record_count == len(resp.data.values)
            assert "discharge_pressure" in resp.provenance.raw_tags


async def test_pi_modes_differ_against_real_simulator():
    signals = {SID: _signal()}
    bindings = {(SID, "pi"): SourceBinding(handle=_webid("P-101A.discharge_pressure"),
                                           raw_unit="psig")}
    win = {"start": "2026-03-06T00:00:00Z", "end": "2026-03-06T00:30:00Z"}
    async with httpx.AsyncClient(base_url=PI_SIM_URL) as http:
        mcp = make_pi_mcp(http_client=http, signals=signals, bindings=bindings)
        async with Client(mcp) as client:
            stored = _parse(await client.call_tool(
                "pi.get_series", {"request": {"signal_id": str(SID), "mode": "stored", **win}}))
            interp = _parse(await client.call_tool(
                "pi.get_series", {"request": {"signal_id": str(SID), "mode": "interpolated", **win}}))
    assert stored.error is None and interp.error is None
    assert all(m.is_interpolated for m in interp.data.values)
    # stored (event-driven) and interpolated (regular grid) return different counts
    assert len(stored.data.values) != len(interp.data.values)
