"""Two entity MCP servers, both fronting the PI Web API (Sprint 2b Track 3 Task 4).

* ``tag`` — PI-historian-backed time-series + metadata (tag.get_history / get_current /
  list_for_asset / get_metadata).
* ``operator_log`` — PI-event-frames-backed operator log (operator_log.list_for_asset / get).

Hand-wired in the KG/asset_hierarchy idiom (explicit ToolResponse via ok_response +
map_source_error), NOT @evidence_tool: base_url arrives per-request via the connection
router (resolved from the request's canonical_id plant + optional connection_id), so each
call opens its own httpx client. Every response carries provenance.connection_id (2b
acceptance #12). NO ``pi.*`` tool name exists.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    ConnectionRouter,
    MalformedResponse,
    NotFound,
    build_server,
    build_time_basis,
    canonical_unit_for,
    map_source_error,
    ok_response,
    register_health,
    to_si,
)
from rca_contracts import (
    Alarm,
    HistorianMode,
    Measurement,
    MeasurementSeries,
    Quality,
    TagDescriptor,
    ToolResponse,
    parse_canonical_id,
)

from .gateway import AssetGateway, CanonicalSlugAssetGateway
from .health import TagHealthProbe
from .models import (
    GetCurrentRequest,
    GetHistoryRequest,
    GetLogRequest,
    GetMetadataRequest,
    ListLogsRequest,
    ListTagsRequest,
    TagInfo,
)

_VERSION = "0.1.0"
_SOURCE_HISTORIAN = "pi_historian"
_SOURCE_EVENT_FRAMES = "pi_event_frames"
_CAT_HISTORIAN = "historian"
_CAT_OPERATOR_LOG = "operator_log"

# get_history mode -> PI Web API stream endpoint (mirrors the old pi connector's map)
_MODE_PATH = {
    HistorianMode.stored: "recorded",
    HistorianMode.interpolated: "interpolated",
}

# PI event-frame template -> canonical alarm priority
_PRIORITY = {"trip": 1, "warning": 3}

HttpClientFactory = Callable[[str], httpx.AsyncClient]


def _default_http_factory(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _role_of(name: str) -> str | None:
    return name.split(".", 1)[1] if "." in name else None


async def _resolve_point(client: httpx.AsyncClient, tag_name: str) -> dict:
    """GET /points?nameFilter=<tag_name>, return the item whose Name matches exactly."""
    resp = await client.get("/points", params={"nameFilter": tag_name})
    resp.raise_for_status()
    items = resp.json().get("Items", [])
    for it in items:
        if it.get("Name") == tag_name:
            return it
    raise NotFound(f"no PI point named {tag_name!r}")


def _tag_descriptor(canonical_id: str, point: dict) -> TagDescriptor:
    units = point.get("EngineeringUnits")
    name = point.get("Name", "")
    return TagDescriptor(
        canonical_id=canonical_id,
        tag_name=name,
        role=_role_of(name),
        source_unit=units,
        qudt_unit=canonical_unit_for(units) if units else None,
        description=point.get("Descriptor"),
    )


# ---------------------------------------------------------------------------
# tag MCP
# ---------------------------------------------------------------------------

def make_tag_mcp(
    *,
    router: ConnectionRouter,
    assets: AssetGateway | None = None,
    http_client_factory: HttpClientFactory | None = None,
    default_base_url: str | None = None,
) -> FastMCP:
    gateway = assets or CanonicalSlugAssetGateway()
    factory = http_client_factory or _default_http_factory
    mcp = build_server("tag")
    register_health(
        mcp, version=_VERSION,
        probe=TagHealthProbe(default_base_url=default_base_url),
    )

    @mcp.tool(name="tag.list_for_asset")
    async def list_for_asset(request: ListTagsRequest) -> ToolResponse[list[TagInfo]]:
        envelope = ToolResponse[list[TagInfo]]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_HISTORIAN, request.connection_id)
            tag = await gateway.tag_for(request.canonical_id)
            async with factory(conn.base_url) as client:
                resp = await client.get("/points", params={"nameFilter": f"{tag}.*"})
                resp.raise_for_status()
                items = resp.json().get("Items", [])
                tags = [
                    TagInfo(
                        tag_name=it.get("Name", ""),
                        role=_role_of(it.get("Name", "")),
                        engineering_units=it.get("EngineeringUnits"),
                        web_id=it.get("WebId", ""),
                        descriptor=it.get("Descriptor"),
                    )
                    for it in items
                ]
            return ok_response(
                tags, tool="tag.list_for_asset", version=_VERSION,
                source=_SOURCE_HISTORIAN, source_query=str(resp.request.url),
                record_count=len(tags), raw_tags=[t.tag_name for t in tags],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="tag.get_history")
    async def get_history(request: GetHistoryRequest) -> ToolResponse[MeasurementSeries]:
        envelope = ToolResponse[MeasurementSeries]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_HISTORIAN, request.connection_id)
            path = _MODE_PATH.get(request.mode)
            if path is None:
                raise NotFound(f"tag.get_history does not serve mode {request.mode.value}")
            async with factory(conn.base_url) as client:
                point = await _resolve_point(client, request.tag_name)
                resp = await client.get(
                    f"/streams/{point['WebId']}/{path}",
                    params={"startTime": _iso(request.start), "endTime": _iso(request.end)},
                )
                resp.raise_for_status()
                items = resp.json().get("Items", [])
            series = _build_series(request.canonical_id, point, items, request.mode)
            return ok_response(
                series, tool="tag.get_history", version=_VERSION,
                source=_SOURCE_HISTORIAN, source_query=str(resp.request.url),
                record_count=len(series.values), raw_tags=[request.tag_name],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="tag.get_current")
    async def get_current(request: GetCurrentRequest) -> ToolResponse[Measurement]:
        envelope = ToolResponse[Measurement]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_HISTORIAN, request.connection_id)
            async with factory(conn.base_url) as client:
                point = await _resolve_point(client, request.tag_name)
                resp = await client.get(f"/streams/{point['WebId']}/value")
                resp.raise_for_status()
                item = resp.json()
            measurement = _build_measurement(point, item)
            return ok_response(
                measurement, tool="tag.get_current", version=_VERSION,
                source=_SOURCE_HISTORIAN, source_query=str(resp.request.url),
                record_count=1, raw_tags=[request.tag_name],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="tag.get_metadata")
    async def get_metadata(request: GetMetadataRequest) -> ToolResponse[TagDescriptor]:
        envelope = ToolResponse[TagDescriptor]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_HISTORIAN, request.connection_id)
            async with factory(conn.base_url) as client:
                point = await _resolve_point(client, request.tag_name)
                resp = await client.get(f"/points/{point['WebId']}")
                resp.raise_for_status()
                detail = resp.json()
            descriptor = _tag_descriptor(request.canonical_id, detail)
            return ok_response(
                descriptor, tool="tag.get_metadata", version=_VERSION,
                source=_SOURCE_HISTORIAN, source_query=str(resp.request.url),
                record_count=1, raw_tags=[request.tag_name],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


def _build_measurement(point: dict, item: dict) -> Measurement:
    units = point.get("EngineeringUnits")
    qudt = canonical_unit_for(units) if units else None
    quality: Quality = "good" if item.get("Good", True) else "uncertain"
    return Measurement(
        timestamp=_parse_ts(item["Timestamp"]),
        value=to_si(item["Value"], units, qudt) if units else item["Value"],
        quality=quality,
        is_interpolated=bool(item.get("IsInterpolated", False)),
    )


def _build_series(
    canonical_id: str, point: dict, items: list[dict], mode: HistorianMode
) -> MeasurementSeries:
    tag = _tag_descriptor(canonical_id, point)
    values = [_build_measurement(point, it) for it in items]
    interpolation: Literal["linear"] | None = (
        "linear" if mode is HistorianMode.interpolated else None
    )
    return MeasurementSeries(
        tag=tag,
        time_basis=build_time_basis(
            source_clock=_SOURCE_HISTORIAN, source_timezone="UTC",
            measured_at=datetime.now(timezone.utc),
        ),
        mode=mode,
        interpolation_method=interpolation,
        values=values,
    )


# ---------------------------------------------------------------------------
# operator_log MCP
# ---------------------------------------------------------------------------

def make_operator_log_mcp(
    *,
    router: ConnectionRouter,
    assets: AssetGateway | None = None,
    http_client_factory: HttpClientFactory | None = None,
    default_base_url: str | None = None,
) -> FastMCP:
    gateway = assets or CanonicalSlugAssetGateway()
    factory = http_client_factory or _default_http_factory
    mcp = build_server("operator_log")
    register_health(
        mcp, version=_VERSION,
        probe=TagHealthProbe(default_base_url=default_base_url),
    )

    @mcp.tool(name="operator_log.list_for_asset")
    async def list_for_asset(request: ListLogsRequest) -> ToolResponse[list[Alarm]]:
        envelope = ToolResponse[list[Alarm]]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_OPERATOR_LOG, request.connection_id)
            tag = await gateway.tag_for(request.canonical_id)
            async with factory(conn.base_url) as client:
                resp = await client.get(
                    "/eventframes",
                    params={"startTime": _iso(request.start), "endTime": _iso(request.end)},
                )
                resp.raise_for_status()
                items = resp.json().get("Items", [])
            alarms = [
                _build_alarm(request.canonical_id, it)
                for it in items
                if _signal_belongs(it.get("Signal", ""), tag)
            ]
            return ok_response(
                alarms, tool="operator_log.list_for_asset", version=_VERSION,
                source=_SOURCE_EVENT_FRAMES, source_query=str(resp.request.url),
                record_count=len(alarms), raw_tags=[a.tag_name or "" for a in alarms],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="operator_log.get")
    async def get(request: GetLogRequest) -> ToolResponse[Alarm]:
        envelope = ToolResponse[Alarm]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_OPERATOR_LOG, request.connection_id)
            async with factory(conn.base_url) as client:
                resp = await client.get(f"/eventframes/{request.log_id}")
                resp.raise_for_status()
                item = resp.json()
            alarm = _build_alarm(request.canonical_id, item)
            return ok_response(
                alarm, tool="operator_log.get", version=_VERSION,
                source=_SOURCE_EVENT_FRAMES, source_query=str(resp.request.url),
                record_count=1, raw_tags=[alarm.tag_name or ""],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


def _signal_belongs(signal: str, tag: str) -> bool:
    """A PI event frame's Signal is "<TAG>.<role>" (or bare "<TAG>")."""
    return signal == tag or signal.startswith(f"{tag}.")


def _build_alarm(canonical_id: str, frame: dict) -> Alarm:
    # Alarm.asset_id is a required AssetID (UUID). At connector altitude we only hold the
    # canonical_id, so we stamp a deterministic uuid5(NAMESPACE_URL, canonical_id) as a
    # stand-in. The real MAR asset UUID is bound during onboarding; tag_name carries the
    # event-frame Signal so downstream can re-key. (See Alarm contract: asset_id required.)
    try:
        ts = _parse_ts(frame["StartTime"])
    except (KeyError, ValueError) as exc:
        raise MalformedResponse(f"event frame missing StartTime: {frame!r}") from exc
    level = str(frame.get("Template", "")).lower()
    return Alarm(
        asset_id=uuid5(NAMESPACE_URL, canonical_id),
        tag_name=frame.get("Signal"),
        timestamp=ts,
        priority=_PRIORITY.get(level, 5),
        state="activated",
        message=frame.get("Name", ""),
        source_system=_SOURCE_EVENT_FRAMES,
    )


__all__ = ["make_tag_mcp", "make_operator_log_mcp"]
