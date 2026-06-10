"""Maximo connector tools (S13.3): read work orders / failure history + idempotent write-back."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from rca_connector_sdk import MalformedResponse, evidence_tool, to_utc
from rca_contracts import AssetID, WorkOrder

_OSLC = "/maxrest/oslc/os"


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


# ---------- requests ----------

class GetWorkOrdersRequest(BaseModel):
    asset_id: AssetID


class GetFailureHistoryRequest(BaseModel):
    asset_id: AssetID


class WritebackRequest(BaseModel):
    asset_id: AssetID
    wonum: str                       # idempotency anchor (sim upserts by wonum)
    description: str
    priority: str = "3"
    problem_code: str | None = None
    work_type: str = "CM"


# ---------- read tools ----------

@evidence_tool(name="maximo.get_workorders", version="0.1.0", source="maximo",
               request=GetWorkOrdersRequest, response=list[WorkOrder])
class MaximoWorkOrders:
    async def fetch(self, ctx, req: GetWorkOrdersRequest):
        location = ctx.source.handle
        resp = await ctx.http.get(
            f"{_OSLC}/mxwo", params={"oslc.where": f'location="{location}"'}
        )
        resp.raise_for_status()
        members = _members(resp.json())
        ctx.prov.record(source_query=str(resp.request.url),
                        raw_tags=[location], record_count=len(members))
        return members

    def translate(self, ctx, raw) -> list[WorkOrder]:
        tz = ctx.config.source_timezone
        asset_id = ctx.request.asset_id
        return [_member_to_workorder(m, asset_id, tz) for m in raw]


@evidence_tool(name="maximo.get_failure_history", version="0.1.0", source="maximo",
               request=GetFailureHistoryRequest, response=list[WorkOrder])
class MaximoFailureHistory:
    async def fetch(self, ctx, req: GetFailureHistoryRequest):
        location = ctx.source.handle
        resp = await ctx.http.get(
            f"{_OSLC}/mxfailrep", params={"oslc.where": f'location="{location}"'}
        )
        resp.raise_for_status()
        members = _members(resp.json())
        ctx.prov.record(source_query=str(resp.request.url),
                        raw_tags=[location], record_count=len(members))
        return members

    def translate(self, ctx, raw) -> list[WorkOrder]:
        tz = ctx.config.source_timezone
        asset_id = ctx.request.asset_id
        out: list[WorkOrder] = []
        for fr in raw:
            fid = fr.get("failurenum") or fr.get("wonum")
            if not fid:
                raise MalformedResponse("failure report missing failurenum/wonum")
            out.append(WorkOrder(
                work_order_id=fid,
                asset_id=asset_id,
                opened_at=_parse_report_date(fr.get("reportdate"), tz),
                closed_at=None,
                priority="",
                status="failure_report",
                failure_code=fr.get("failurecode"),     # ISO where present; legacy codes pass through
                description=fr.get("description", ""),
                source_system="maximo",
            ))
        return out


# ---------- write tools ----------

@evidence_tool(name="maximo.preview_writeback", version="0.1.0", source="maximo",
               request=WritebackRequest, response=WorkOrder, mutating=False)  # dry-run: no write
class MaximoPreviewWriteback:
    async def fetch(self, ctx, req: WritebackRequest):
        # dry-run: no source call, but provenance still records the (non-)action
        ctx.prov.record(source_query="(preview: no write performed)",
                        raw_tags=[ctx.source.handle], record_count=1)
        return None

    def translate(self, ctx, raw) -> WorkOrder:
        return _request_to_workorder(ctx.request, ctx.request.asset_id)


@evidence_tool(name="maximo.commit_writeback", version="0.1.0", source="maximo",
               request=WritebackRequest, response=WorkOrder, mutating=True)
class MaximoCommitWriteback:
    async def fetch(self, ctx, req: WritebackRequest):
        body = {
            "wonum": req.wonum, "location": ctx.source.handle, "description": req.description,
            "status": "WAPPR", "wopriority": req.priority, "problemcode": req.problem_code,
            "worktype": req.work_type,
        }
        resp = await ctx.http.post(f"{_OSLC}/mxwo", json=body)  # idempotent: sim upserts by wonum
        resp.raise_for_status()
        ctx.prov.record(source_query=f"POST {resp.request.url}",
                        raw_tags=[req.wonum], record_count=1)
        return resp.json()

    def translate(self, ctx, raw) -> WorkOrder:
        # commit response is a just-created WO without a reportdate -> now() (acceptable fallback)
        return _member_to_workorder(raw, ctx.request.asset_id, ctx.config.source_timezone)


# ---------- mapping helpers ----------

def _member_to_workorder(m: dict, asset_id, tz: str) -> WorkOrder:
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


def _request_to_workorder(req: WritebackRequest, asset_id) -> WorkOrder:
    return WorkOrder(
        work_order_id=req.wonum,
        asset_id=asset_id,
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
        priority=req.priority,
        status="WAPPR",
        failure_code=None,
        description=req.description,
        source_system="maximo",
    )


__all__ = [
    "GetWorkOrdersRequest", "GetFailureHistoryRequest", "WritebackRequest",
    "MaximoWorkOrders", "MaximoFailureHistory",
    "MaximoPreviewWriteback", "MaximoCommitWriteback",
]
