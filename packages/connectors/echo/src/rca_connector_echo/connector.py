"""The echo connector — proves the SDK: implement only fetch() + translate()."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from rca_connector_sdk import RawPoint, build_measurement_series, evidence_tool
from rca_contracts import HistorianMode, MeasurementSeries, SignalID


class GetSeriesRequest(BaseModel):
    signal_id: SignalID
    mode: HistorianMode = HistorianMode.stored


@evidence_tool(
    name="echo.get_series", version="0.1.0", source="echo",
    request=GetSeriesRequest, response=MeasurementSeries,
)
class EchoSeries:
    async def fetch(self, ctx, req: GetSeriesRequest):
        resp = await ctx.http.get(f"/series/{ctx.source.handle}")   # source handle from the resolver
        resp.raise_for_status()                       # 5xx/4xx -> ToolError via the SDK
        body = resp.json()
        ctx.prov.record(
            source_query=str(resp.request.url),
            raw_tags=[ctx.signal.role],
            record_count=len(body["points"]),
        )
        return body["points"]

    def translate(self, ctx, raw) -> MeasurementSeries:
        points = [RawPoint(timestamp=datetime.fromisoformat(p["t"]), value=p["v"]) for p in raw]
        return build_measurement_series(ctx, points, mode=ctx.request.mode)


__all__ = ["GetSeriesRequest", "EchoSeries"]
