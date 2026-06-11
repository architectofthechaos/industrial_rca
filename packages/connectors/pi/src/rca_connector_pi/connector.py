"""The PI connector's tools. S13.2 slice: pi.get_series."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel
from rca_connector_sdk import NotFound, RawPoint, build_measurement_series, evidence_tool
from rca_contracts import Alarm, HistorianMode, MeasurementSeries, Quality

# get_series mode -> PI Web API stream endpoint
_MODE_PATH = {
    HistorianMode.stored: "recorded",
    HistorianMode.interpolated: "interpolated",
}

# canonical aggregation method -> PI summaryType
_SUMMARY_TYPE = {
    "avg": "Average", "min": "Minimum", "max": "Maximum",
    "stddev": "StdDev", "count": "Count",
}

# PI event-frame level -> canonical alarm priority
_PRIORITY = {"trip": 1, "warning": 3}


class GetSeriesRequest(BaseModel):
    signal_id: UUID
    start: AwareDatetime
    end: AwareDatetime
    mode: HistorianMode = HistorianMode.stored


class GetSummaryRequest(BaseModel):
    signal_id: UUID
    start: AwareDatetime
    end: AwareDatetime
    aggregation_method: Literal["avg", "min", "max", "stddev", "count"] = "avg"
    aggregation_interval: timedelta = timedelta(minutes=15)


class GetEventFramesRequest(BaseModel):
    signal_id: UUID
    start: AwareDatetime
    end: AwareDatetime


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@evidence_tool(
    name="pi.get_series", version="0.1.0", source="pi",
    request=GetSeriesRequest, response=MeasurementSeries,
)
class PiSeries:
    async def fetch(self, ctx, req: GetSeriesRequest):
        path = _MODE_PATH.get(req.mode)
        if path is None:
            raise NotFound(f"pi.get_series does not serve mode {req.mode}; use pi.get_summary")
        web_id = ctx.source.handle
        resp = await ctx.http.get(
            f"/streams/{web_id}/{path}",
            params={"startTime": _iso(req.start), "endTime": _iso(req.end)},
        )
        resp.raise_for_status()                       # PI 5xx/4xx -> ToolError via the SDK
        items = resp.json()["Items"]
        ctx.prov.record(
            source_query=str(resp.request.url),
            raw_tags=[ctx.tag.role],
            record_count=len(items),
        )
        return items

    def translate(self, ctx, raw) -> MeasurementSeries:
        points: list[RawPoint] = []
        for it in raw:
            ts = datetime.fromisoformat(it["Timestamp"].replace("Z", "+00:00"))
            quality: Quality = "good" if it.get("Good", True) else "uncertain"
            points.append(RawPoint(
                timestamp=ts,
                value=it["Value"],
                quality=quality,
                is_interpolated=bool(it.get("IsInterpolated", False)),
            ))
        return build_measurement_series(ctx, points, mode=ctx.request.mode)


@evidence_tool(
    name="pi.get_summary", version="0.1.0", source="pi",
    request=GetSummaryRequest, response=MeasurementSeries,
)
class PiSummary:
    async def fetch(self, ctx, req: GetSummaryRequest):
        resp = await ctx.http.get(
            f"/streams/{ctx.source.handle}/summary",
            params={
                "startTime": _iso(req.start), "endTime": _iso(req.end),
                "summaryType": _SUMMARY_TYPE[req.aggregation_method],
                "summaryDuration": f"{int(req.aggregation_interval.total_seconds())}s",
            },
        )
        resp.raise_for_status()
        items = resp.json()["Items"]
        ctx.prov.record(source_query=str(resp.request.url),
                        raw_tags=[ctx.tag.role], record_count=len(items))
        return items

    def translate(self, ctx, raw) -> MeasurementSeries:
        # each PI summary item nests the aggregate under "Value"
        points = [
            RawPoint(
                timestamp=datetime.fromisoformat(it["Value"]["Timestamp"].replace("Z", "+00:00")),
                value=it["Value"]["Value"],
            )
            for it in raw
        ]
        req = ctx.request
        return build_measurement_series(
            ctx, points, mode=HistorianMode.aggregated,
            aggregation_method=req.aggregation_method,
            aggregation_interval=req.aggregation_interval,
        )


@evidence_tool(
    name="pi.get_event_frames", version="0.1.0", source="pi",
    request=GetEventFramesRequest, response=list[Alarm],
)
class PiEventFrames:
    async def fetch(self, ctx, req: GetEventFramesRequest):
        resp = await ctx.http.get(
            "/eventframes",
            params={"startTime": _iso(req.start), "endTime": _iso(req.end)},
        )
        resp.raise_for_status()
        items = resp.json()["Items"]
        ctx.prov.record(source_query=str(resp.request.url),
                        raw_tags=[ctx.tag.role], record_count=len(items))
        return items

    def translate(self, ctx, raw) -> list[Alarm]:
        tag = ctx.tag
        # event-frame requests are tag-scoped; the request's entity id is the asset under audit
        asset_id = ctx.request.signal_id
        alarms: list[Alarm] = []
        for it in raw:
            level = str(it.get("Template", "")).lower()
            alarms.append(Alarm(
                asset_id=asset_id,
                tag_name=tag.tag_name,
                timestamp=datetime.fromisoformat(it["StartTime"].replace("Z", "+00:00")),
                priority=_PRIORITY.get(level, 5),
                state="activated",
                message=it.get("Name", ""),
                source_system="pi",
            ))
        return alarms


__all__ = [
    "GetSeriesRequest", "GetSummaryRequest", "GetEventFramesRequest",
    "PiSeries", "PiSummary", "PiEventFrames",
]
