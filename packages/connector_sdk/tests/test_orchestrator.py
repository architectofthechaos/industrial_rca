"""Orchestrator tests: the @evidence_tool pipeline, exercised directly (no MCP).

Proves hard-fail by construction: success requires recorded provenance + valid
output; every failure path becomes a ToolError with no data leaked.
"""
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from rca_contracts import (
    HistorianMode,
    MeasurementSeries,
    PressureReference,
    TagDescriptor,
)

from rca_connector_sdk.context import RawPoint, ToolConfig, ToolDeps
from rca_connector_sdk.orchestrator import evidence_tool
from rca_connector_sdk.ports import InMemoryTagResolver, SourceBinding
from rca_connector_sdk.series import build_measurement_series

UTC = timezone.utc
SID = uuid4()


class SeriesRequest(BaseModel):
    signal_id: UUID
    mode: HistorianMode = HistorianMode.stored


def _tag() -> TagDescriptor:
    return TagDescriptor(
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        tag_name="P-101A.discharge_pressure",
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.absolute,
    )


def _deps(raw_unit: str = "bar") -> ToolDeps:
    resolver = InMemoryTagResolver(
        {SID: _tag()},
        {(SID, "echo"): SourceBinding(handle="echo-handle", raw_unit=raw_unit)},
    )
    return ToolDeps(
        tag_resolver=resolver,
        config=ToolConfig(source_timezone="UTC", retry_attempts=2),
    )


@evidence_tool(name="echo.series", version="0.1.0", source="echo",
               request=SeriesRequest, response=MeasurementSeries)
class _GoodTool:
    async def fetch(self, ctx, req):
        ctx.prov.record(source_query="GET /echo", raw_tags=["RAW.TAG"], record_count=2)
        return [(datetime(2026, 3, 1, 0, 0, 0), 1.0), (datetime(2026, 3, 1, 0, 0, 1), 2.0)]

    def translate(self, ctx, raw):
        points = [RawPoint(timestamp=t, value=v) for t, v in raw]
        return build_measurement_series(ctx, points, mode=ctx.request.mode)


@evidence_tool(name="echo.noprov", version="0.1.0", source="echo",
               request=SeriesRequest, response=MeasurementSeries)
class _ForgetsProvenance:
    async def fetch(self, ctx, req):
        return [(datetime(2026, 3, 1, tzinfo=UTC), 1.0)]   # never records provenance

    def translate(self, ctx, raw):
        points = [RawPoint(timestamp=t, value=v) for t, v in raw]
        return build_measurement_series(ctx, points, mode=ctx.request.mode)


@evidence_tool(name="echo.down", version="0.1.0", source="echo",
               request=SeriesRequest, response=MeasurementSeries)
class _SourceDown:
    async def fetch(self, ctx, req):
        from rca_connector_sdk.errors import SourceUnavailable
        raise SourceUnavailable("connection refused")

    def translate(self, ctx, raw):  # pragma: no cover
        return []


async def test_success_converts_units_and_stamps_provenance():
    tool = _GoodTool.bind(_deps(raw_unit="bar"))
    resp = await tool(SeriesRequest(signal_id=SID))
    assert resp.error is None
    assert resp.data is not None and isinstance(resp.data, MeasurementSeries)
    assert resp.data.values[0].value == pytest.approx(100_000.0)   # 1 bar -> Pa
    assert resp.data.values[0].timestamp.tzinfo is not None         # UTC-aware
    assert resp.provenance.record_count == 2 and resp.provenance.raw_tags == ["RAW.TAG"]


async def test_missing_provenance_yields_error_not_data():
    tool = _ForgetsProvenance.bind(_deps())
    resp = await tool(SeriesRequest(signal_id=SID))
    assert resp.data is None
    assert resp.error is not None and resp.error.code == "internal_error"


async def test_ambiguous_unit_becomes_tool_error():
    tool = _GoodTool.bind(_deps(raw_unit="psig"))   # gauge pressure -> refused
    resp = await tool(SeriesRequest(signal_id=SID))
    assert resp.data is None and resp.error.code == "unit_conversion_ambiguous"


async def test_unresolved_signal_becomes_tool_error():
    tool = _GoodTool.bind(_deps())
    resp = await tool(SeriesRequest(signal_id=uuid4()))   # not in resolver
    assert resp.data is None and resp.error.code == "unresolved_signal"


async def test_source_failure_after_retries_becomes_tool_error():
    tool = _SourceDown.bind(_deps())
    resp = await tool(SeriesRequest(signal_id=SID))
    assert resp.data is None and resp.error.code == "source_unavailable" and resp.error.retryable is True
