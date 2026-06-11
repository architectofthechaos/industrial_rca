"""S13.2 PI connector test: pi.get_series end-to-end through MCP.

Drives a minimal in-test PI Web API fake (canned PI-shaped responses) so the test
is hermetic. Real connector x EPIC-002-simulator parity is S13.8 (+ a live smoke).
Exercises the headline gauge-pressure path: psig -> Pa with pressure_reference=gauge.
"""
import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import (
    Alarm,
    MeasurementSeries,
    PressureReference,
    TagDescriptor,
    ToolResponse,
)

from rca_connector_pi.server import make_pi_mcp

SID = uuid4()
DOWN = uuid4()
WEBID = "WEBID-P101A-DISCH"
WEBID_DOWN = "WEBID-DOWN"


def _signal(signal_id) -> TagDescriptor:
    return TagDescriptor(
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        tag_name="P-101A.discharge_pressure",
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.gauge,            # PI emits psig (gauge)
    )


def _build_pi_fake() -> FastAPI:
    app = FastAPI(title="PI fake")

    def _items(interpolated: bool):
        flag = {"IsInterpolated": True} if interpolated else {}
        return {"Items": [
            {"Timestamp": "2026-03-06T00:00:00Z", "Value": 14.5, "Good": True, **flag},
            {"Timestamp": "2026-03-06T00:01:00Z", "Value": 14.7, "Good": True, **flag},
        ]}

    @app.get("/streams/{web_id}/recorded")
    def recorded(web_id: str, startTime: str, endTime: str):
        if web_id == WEBID_DOWN:
            raise HTTPException(status_code=503, detail="PI down")
        return _items(interpolated=False)

    @app.get("/streams/{web_id}/interpolated")
    def interpolated(web_id: str, startTime: str, endTime: str, interval: str = "60s"):
        return _items(interpolated=True)

    @app.get("/streams/{web_id}/summary")
    def summary(web_id: str, startTime: str, endTime: str,
                summaryType: str = "Average", summaryDuration: str = "900s"):
        return {"Items": [
            {"Type": summaryType,
             "Value": {"Timestamp": "2026-03-06T00:00:00Z", "Value": 14.6, "Good": True}},
            {"Type": summaryType,
             "Value": {"Timestamp": "2026-03-06T00:15:00Z", "Value": 14.8, "Good": True}},
        ]}

    @app.get("/eventframes")
    def eventframes(startTime: str, endTime: str):
        return {"Items": [
            {"Name": "ALM-2026-03-06-001", "StartTime": "2026-03-06T00:05:00Z",
             "EndTime": "2026-03-06T00:06:00Z", "Template": "warning"},
        ]}

    return app


def _deps_signals():
    signals = {SID: _signal(SID), DOWN: _signal(DOWN)}
    bindings = {
        (SID, "pi"): SourceBinding(handle=WEBID, raw_unit="psig"),
        (DOWN, "pi"): SourceBinding(handle=WEBID_DOWN, raw_unit="psig"),
    }
    return signals, bindings


def _parse(result) -> "ToolResponse[MeasurementSeries]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[MeasurementSeries].model_validate_json(json.dumps(payload))


async def test_pi_get_series_success_interpolated_and_error():
    transport = httpx.ASGITransport(app=_build_pi_fake())
    signals, bindings = _deps_signals()
    async with httpx.AsyncClient(transport=transport, base_url="http://pi") as http:
        mcp = make_pi_mcp(http_client=http, signals=signals, bindings=bindings)
        async with Client(mcp) as client:
            assert "pi.get_series" in {t.name for t in await client.list_tools()}

            win = {"start": "2026-03-06T00:00:00Z", "end": "2026-03-06T01:00:00Z"}

            # --- stored: psig -> Pa (gauge), provenance present ---
            ok = await client.call_tool(
                "pi.get_series", {"request": {"signal_id": str(SID), "mode": "stored", **win}}
            )
            resp = _parse(ok)
            assert resp.error is None and resp.data is not None
            assert len(resp.data.values) == 2
            assert resp.data.values[0].value == pytest.approx(14.5 * 6_894.757293168)  # psig->Pa
            assert resp.data.values[0].timestamp.tzinfo is not None
            assert all(not m.is_interpolated for m in resp.data.values)
            assert resp.provenance.record_count == 2
            assert "discharge_pressure" in resp.provenance.raw_tags

            # --- interpolated: flag carried through ---
            interp = await client.call_tool(
                "pi.get_series", {"request": {"signal_id": str(SID), "mode": "interpolated", **win}}
            )
            iresp = _parse(interp)
            assert iresp.data.mode.value == "interpolated"
            assert all(m.is_interpolated for m in iresp.data.values)

            # --- source 503 -> ToolError, no data ---
            bad = await client.call_tool(
                "pi.get_series", {"request": {"signal_id": str(DOWN), "mode": "stored", **win}}
            )
            berr = _parse(bad)
            assert berr.data is None and berr.error.code == "source_unavailable"


async def test_pi_get_summary_returns_aggregated_series():
    transport = httpx.ASGITransport(app=_build_pi_fake())
    signals, bindings = _deps_signals()
    async with httpx.AsyncClient(transport=transport, base_url="http://pi") as http:
        mcp = make_pi_mcp(http_client=http, signals=signals, bindings=bindings)
        async with Client(mcp) as client:
            res = await client.call_tool("pi.get_summary", {"request": {
                "signal_id": str(SID), "start": "2026-03-06T00:00:00Z",
                "end": "2026-03-06T01:00:00Z", "aggregation_method": "avg",
            }})
            resp = _parse(res)
            assert resp.error is None
            assert resp.data.mode.value == "aggregated"
            assert resp.data.aggregation_method == "avg"
            assert len(resp.data.values) == 2
            assert resp.data.values[0].value == pytest.approx(14.6 * 6_894.757293168)


async def test_pi_get_event_frames_returns_alarms():
    transport = httpx.ASGITransport(app=_build_pi_fake())
    signals, bindings = _deps_signals()
    async with httpx.AsyncClient(transport=transport, base_url="http://pi") as http:
        mcp = make_pi_mcp(http_client=http, signals=signals, bindings=bindings)
        async with Client(mcp) as client:
            res = await client.call_tool("pi.get_event_frames", {"request": {
                "signal_id": str(SID), "start": "2026-03-06T00:00:00Z",
                "end": "2026-03-06T01:00:00Z",
            }})
            payload = res.structured_content if res.structured_content is not None else res.data
            import json
            resp = ToolResponse[list[Alarm]].model_validate_json(json.dumps(payload))
            assert resp.error is None and resp.data is not None
            assert len(resp.data) == 1
            assert resp.data[0].message == "ALM-2026-03-06-001"
            assert resp.data[0].priority == 3 and resp.data[0].source_system == "pi"
