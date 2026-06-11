"""The ``work_order`` entity MCP — canonical CMMS work orders, Maximo-backed (Sprint 2b Track 3).

Hand-wired in the tag/operator_log idiom (explicit ToolResponse via ok_response +
map_source_error), NOT @evidence_tool: base_url arrives per-request via the connection
router (resolved from the request's plant + optional connection_id), so each call opens its
own httpx client. Every response carries provenance.connection_id (2b acceptance #12). NO
``maximo.*`` tool name exists.

Tools:
* work_order.list_for_asset{canonical_id} -> list[WorkOrder]  (cmms location via AssetGateway)
* work_order.get{work_order_id, plant_id} -> WorkOrder        (single WO by wonum)
* work_order.list_recent{plant_id, limit} -> list[WorkOrder]  (newest-first by reportdate)
* work_order.create{...} -> WorkOrder        (Sprint 3 WI6 — follow-up WO; POSTs mxwo,
  deterministic wonum from references for idempotency)

The WorkOrder translation (Maximo member dict -> canonical WorkOrder) is reused verbatim
from the old maximo connector. WorkOrder.asset_id is a required AssetID (UUID); at connector
altitude we only hold a canonical_id (or none at all), so we stamp a deterministic
uuid5(NAMESPACE_URL, key) as a stand-in — the real MAR asset UUID is bound during onboarding.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    AssetGateway,
    CanonicalSlugAssetGateway,
    ConnectionRouter,
    MalformedResponse,
    NotFound,
    build_server,
    map_source_error,
    ok_response,
    register_health,
    to_utc,
)
from rca_contracts import ToolResponse, WorkOrder, parse_canonical_id

from .health import WorkOrderHealthProbe
from .models import (
    CreateWorkOrderRequest,
    GetWorkOrderRequest,
    ListForAssetRequest,
    ListRecentRequest,
)

_VERSION = "0.1.0"
_SOURCE = "maximo"
_CAT_CMMS = "cmms"
_OSLC = "/maxrest/oslc/os"
# Maximo worktype codes the sim recognizes (PM=preventive, CM=corrective, INSP=inspection).
_WORK_TYPE_MAP = {"PM": "PM", "CM": "CM", "INSPECTION": "INSP", "INSP": "INSP"}
# Maximo emits local-time-without-TZ reportdates; this is the reference site tz. (A future
# MAR/connection binding can carry per-connection timezone; MVP uses the fleet default.)
_SOURCE_TZ = "America/Chicago"   # TODO(track1): source from ConnectionInfo.extra_config

HttpClientFactory = Callable[[str], httpx.AsyncClient]


def _default_http_factory(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def _members(resp_json: dict) -> list[dict]:
    # OSLC may omit/null `member` for an empty result — treat as zero rows, not an error.
    members = resp_json.get("member")
    return members if isinstance(members, list) else []


def _parse_report_date(value: str | None, tz: str) -> datetime:
    """Maximo local-time reportdate -> UTC. Missing -> now() (acceptable fallback, e.g. a
    freshly-created WO); malformed -> a loud validation error (never silently fabricated)."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        return to_utc(datetime.fromisoformat(value), tz)
    except ValueError as exc:
        raise MalformedResponse(f"unparseable reportdate {value!r}") from exc


def _member_to_workorder(m: dict, asset_id: UUID, tz: str) -> WorkOrder:
    """Maximo mxwo member -> canonical WorkOrder (reused from the old maximo connector)."""
    wonum = m.get("wonum")
    if not wonum:
        raise MalformedResponse("work order missing wonum")
    return WorkOrder(
        work_order_id=wonum,
        asset_id=asset_id,
        opened_at=_parse_report_date(m.get("reportdate"), tz),
        closed_at=None,
        priority=str(m.get("wopriority", "") or ""),
        status=str(m.get("status", "") or ""),
        failure_code=m.get("failurecode"),
        description=m.get("description", ""),
        source_system="maximo",
    )


def _stamp_asset_id(key: str) -> UUID:
    """Deterministic stand-in AssetID until MAR binds the real UUID (see module docstring)."""
    return uuid5(NAMESPACE_URL, key)


def _mint_wonum(references: dict) -> str:
    """Deterministic wonum from (probe_run_id, conclusion_id) so re-running the close phase
    upserts the SAME WO (§6.3 idempotency). The Maximo sim upserts by wonum, so a stable
    wonum means a second POST overwrites rather than duplicates."""
    probe_run_id = references.get("probe_run_id", "")
    conclusion_id = references.get("conclusion_id", "")
    digest = uuid5(NAMESPACE_URL, f"rca-wo:{probe_run_id}:{conclusion_id}").hex[:10].upper()
    return f"WO-RCA-{digest}"


def make_work_order_mcp(
    *,
    router: ConnectionRouter,
    assets: AssetGateway | None = None,
    http_client_factory: HttpClientFactory | None = None,
    default_base_url: str | None = None,
) -> FastMCP:
    # DEFAULT gateway is CanonicalSlugAssetGateway, whose source_handle raises NotFound — so
    # list_for_asset returns a clean ToolError (not_found) until MAR wiring supplies the cmms
    # location. Inject a StaticAssetGateway(handles=...) for hermetic tests / explicit bindings.
    gateway = assets or CanonicalSlugAssetGateway()
    factory = http_client_factory or _default_http_factory
    mcp = build_server("work_order")
    register_health(
        mcp, version=_VERSION,
        probe=WorkOrderHealthProbe(default_base_url=default_base_url),
    )

    @mcp.tool(name="work_order.list_for_asset")
    async def list_for_asset(request: ListForAssetRequest) -> ToolResponse[list[WorkOrder]]:
        envelope = ToolResponse[list[WorkOrder]]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_CMMS, request.connection_id)
            location = await gateway.source_handle(request.canonical_id, _CAT_CMMS)
            asset_id = _stamp_asset_id(request.canonical_id)
            async with factory(conn.base_url) as client:
                # same filter the old maximo.get_workorders sent: oslc.where location="<loc>"
                resp = await client.get(
                    f"{_OSLC}/mxwo", params={"oslc.where": f'location="{location}"'}
                )
                resp.raise_for_status()
                members = _members(resp.json())
            work_orders = [_member_to_workorder(m, asset_id, _SOURCE_TZ) for m in members]
            return ok_response(
                work_orders, tool="work_order.list_for_asset", version=_VERSION,
                source=_SOURCE, source_query=str(resp.request.url),
                record_count=len(work_orders), raw_tags=[location],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="work_order.get")
    async def get(request: GetWorkOrderRequest) -> ToolResponse[WorkOrder]:
        envelope = ToolResponse[WorkOrder]
        try:
            conn = await router.active(request.plant_id, _CAT_CMMS, request.connection_id)
            asset_id = _stamp_asset_id(f"wonum:{request.work_order_id}")
            async with factory(conn.base_url) as client:
                # the sim has no single-WO endpoint: query mxwo filtered by wonum, pick the match
                resp = await client.get(
                    f"{_OSLC}/mxwo",
                    params={"oslc.where": f'wonum="{request.work_order_id}"'},
                )
                resp.raise_for_status()
                members = _members(resp.json())
            match = next(
                (m for m in members if m.get("wonum") == request.work_order_id), None
            )
            if match is None:
                # absent wonum is "not found" — distinct from a malformed member, which
                # _member_to_workorder raises as MalformedResponse (a data error).
                raise NotFound(f"no work order with wonum {request.work_order_id!r}")
            work_order = _member_to_workorder(match, asset_id, _SOURCE_TZ)
            return ok_response(
                work_order, tool="work_order.get", version=_VERSION,
                source=_SOURCE, source_query=str(resp.request.url),
                record_count=1, raw_tags=[request.work_order_id],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="work_order.list_recent")
    async def list_recent(request: ListRecentRequest) -> ToolResponse[list[WorkOrder]]:
        envelope = ToolResponse[list[WorkOrder]]
        try:
            conn = await router.active(request.plant_id, _CAT_CMMS, request.connection_id)
            async with factory(conn.base_url) as client:
                # The Maximo sim's OSLC surface has no order-by; fetch all then sort/limit
                # client-side by reportdate desc (LIMITATION: not pushed down to the source).
                resp = await client.get(f"{_OSLC}/mxwo")
                resp.raise_for_status()
                members = _members(resp.json())
            work_orders = [
                _member_to_workorder(m, _stamp_asset_id(f"wonum:{m.get('wonum')}"), _SOURCE_TZ)
                for m in members
            ]
            work_orders.sort(key=lambda w: w.opened_at, reverse=True)
            work_orders = work_orders[: max(request.limit, 0)]
            return ok_response(
                work_orders, tool="work_order.list_recent", version=_VERSION,
                source=_SOURCE, source_query=str(resp.request.url),
                record_count=len(work_orders),
                raw_tags=[w.work_order_id for w in work_orders],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="work_order.create")
    async def create(request: CreateWorkOrderRequest) -> ToolResponse[WorkOrder]:
        envelope = ToolResponse[WorkOrder]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_CMMS, request.connection_id)
            location = await gateway.source_handle(request.canonical_id, _CAT_CMMS)
            wonum = _mint_wonum(request.references)
            worktype = _WORK_TYPE_MAP.get(request.work_type.upper(), "CM")
            reported = (request.reported_at or datetime.now(timezone.utc))
            # Maximo emits/accepts local-time-without-tz reportdates; mirror that for round-trip.
            record = {
                "wonum": wonum,
                "location": location,
                "description": request.description,
                "worktype": worktype,
                "wopriority": request.priority,
                "status": "WAPPR",                 # created, waiting approval (not yet COMP)
                "reportdate": reported.astimezone(timezone.utc)
                .replace(tzinfo=None).isoformat(),
                "rca_probe_run_id": request.references.get("probe_run_id"),
                "rca_conclusion_id": request.references.get("conclusion_id"),
                "rca_failure_event_id": request.references.get("failure_event_id"),
                "reportedby": request.requested_by,
            }
            asset_id = _stamp_asset_id(request.canonical_id)
            async with factory(conn.base_url) as client:
                resp = await client.post(f"{_OSLC}/mxwo", json=record)
                resp.raise_for_status()
                created = resp.json()
            work_order = _member_to_workorder(created, asset_id, _SOURCE_TZ)
            return ok_response(
                work_order, tool="work_order.create", version=_VERSION, source=_SOURCE,
                source_query=str(resp.request.url), record_count=1,
                raw_tags=[wonum, location], connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


__all__ = ["make_work_order_mcp"]
