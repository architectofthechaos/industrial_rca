"""Wire the MQTT/UNS connector into a FastMCP server.

Unlike the other connectors, the UNS read tools (`uns.browse_namespace`,
`uns.get_recent_messages`) read a *local* cache that the background `UnsService`
fills — there is no per-request round-trip to a source. The `@evidence_tool`
orchestrator instantiates its impl class with no args, so it can't be handed the
shared `SubscriptionState`; therefore these two tools are hand-wired on FastMCP.
They still honor the universal invariants — provenance is built via the SDK's
hard-fail `ProvenanceAccumulator` and the result is a `ToolResponse[T]` envelope —
so "no data without provenance" holds here too.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import BaseModel
from rca_connector_sdk import (
    ProvenanceAccumulator,
    SubscriptionState,
    build_server,
    map_source_error,
    register_health,
)
from rca_contracts import ToolResponse

from .health import MqttHealthProbe
from .models import (
    DeviceSnapshot,
    MetricSnapshot,
    NamespaceTree,
    RecentMessages,
    UnsMessage,
    UnsMessageMetric,
)


class BrowseRequest(BaseModel):
    group_id: str | None = None        # reserved filter (single group in the MVP)


class RecentRequest(BaseModel):
    device_id: str | None = None       # filter to one device
    limit: int = 50


def _ts(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _cache_response(envelope: Any, data: Any, *, tool_name: str, source_query: str,
                    record_count: int, raw_tags: list[str]) -> Any:
    """Build a ToolResponse[T] for a cache-read tool, enforcing provenance (hard-fail)."""
    prov = ProvenanceAccumulator()
    prov.record(source_query=source_query, record_count=record_count, raw_tags=raw_tags)
    provenance = prov.build(
        tool_name=tool_name, tool_version="0.1.0", source="mqtt",
        queried_at=datetime.now(timezone.utc), response_id=uuid4(),
    )
    return envelope.ok(data, provenance)


def _build_tree(state: SubscriptionState) -> NamespaceTree:
    # Snapshot the alias maps before iterating: the paho ingest thread mutates these dicts
    # concurrently, so iterating them live could raise "dict changed size during iteration".
    aliases = {dev: dict(amap) for dev, amap in dict(state.metadata.get("aliases", {})).items()}
    devices: list[DeviceSnapshot] = []
    for device in sorted(aliases):
        metrics: list[MetricSnapshot] = []
        for alias, name in sorted(aliases[device].items(), key=lambda kv: kv[1]):
            cur = state.current_values.get(f"{device}/{name}")   # single get: atomic under the GIL
            metrics.append(MetricSnapshot(
                name=name, alias=alias,
                value=cur["value"] if cur else None,
                timestamp=_ts(cur["timestamp_ms"]) if cur else None,
            ))
        devices.append(DeviceSnapshot(device_id=device, metrics=metrics))
    return NamespaceTree(
        group_id=state.metadata.get("group_id", ""),
        node_id=state.metadata.get("node_id", ""),
        devices=devices,
    )


def _build_recent(state: SubscriptionState, *, device_id: str | None, limit: int) -> RecentMessages:
    rows = state.recent.snapshot()
    if device_id is not None:
        rows = [r for r in rows if r.get("device_id") == device_id]
    rows = rows[-limit:] if limit >= 0 else rows
    messages = [
        UnsMessage(
            topic=r["topic"], group_id=r["group_id"], node_id=r["node_id"],
            device_id=r.get("device_id"), msgtype=r["msgtype"], seq=r["seq"],
            timestamp=_ts(r["timestamp_ms"]),   # honest: None if the frame carried no timestamp,
            metrics=[UnsMessageMetric(**m) for m in r["metrics"]],   # never a fabricated now()
        )
        for r in rows
    ]
    return RecentMessages(messages=messages)


_VERSION = "0.1.0"


def make_mqtt_mcp(
    *,
    state: SubscriptionState,
    broker_host: str = "localhost",
    broker_port: int = 1883,
    paho_health_client_class: Any | None = None,   # inject a fake paho client for tests
    health_reachable_check: Any | None = None,     # inject a TCP pre-check stub for tests
) -> FastMCP:
    """Build the MQTT/UNS MCP server reading the cache `state` (filled by UnsService)."""
    mcp = build_server("mqtt-uns-connector")

    @mcp.tool(name="uns.browse_namespace")
    async def browse_namespace(request: BrowseRequest) -> ToolResponse[NamespaceTree]:
        envelope = ToolResponse[NamespaceTree]
        try:
            tree = _build_tree(state)
            raw_tags = [f"{d.device_id}/{m.name}" for d in tree.devices for m in d.metrics]
            return _cache_response(
                envelope, tree,
                tool_name="uns.browse_namespace",
                source_query=f"uns cache browse (filter={request.group_id})",
                record_count=len(raw_tags), raw_tags=raw_tags,
            )
        except Exception as exc:  # noqa: BLE001 — boundary: every failure becomes a ToolError
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="uns.get_recent_messages")
    async def get_recent_messages(request: RecentRequest) -> ToolResponse[RecentMessages]:
        envelope = ToolResponse[RecentMessages]
        try:
            recent = _build_recent(state, device_id=request.device_id, limit=request.limit)
            raw_tags = sorted({r.topic for r in recent.messages})
            return _cache_response(
                envelope, recent,
                tool_name="uns.get_recent_messages",
                source_query=f"uns cache recent (device={request.device_id}, limit={request.limit})",
                record_count=len(recent.messages), raw_tags=raw_tags,
            )
        except Exception as exc:  # noqa: BLE001 — boundary: every failure becomes a ToolError
            return envelope.fail(map_source_error(exc))

    register_health(
        mcp,
        version=_VERSION,
        probe=MqttHealthProbe(
            broker_host=broker_host,
            broker_port=broker_port,
            paho_client_class=paho_health_client_class,
            reachable_check=health_reachable_check,
        ),
    )
    return mcp


__all__ = ["make_mqtt_mcp", "BrowseRequest", "RecentRequest"]
