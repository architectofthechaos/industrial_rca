"""Request models for the work_order entity MCP (Sprint 2b Track 3 Task 5).

list_for_asset is canonical_id-scoped (the router resolves the cmms connection from the
plant). get / list_recent take a vendor wonum / plant_id directly — a payload-level vendor
id is allowed where there is no canonical_id (per the entity-tool spec). No request ever
carries a base_url: the connection registry owns endpoints, not the caller.
"""
from __future__ import annotations

from pydantic import BaseModel


class ListForAssetRequest(BaseModel):
    canonical_id: str
    connection_id: str | None = None


class GetWorkOrderRequest(BaseModel):
    work_order_id: str          # wonum — a vendor id, allowed at payload level
    plant_id: str               # needed for routing (no canonical_id to derive it)
    connection_id: str | None = None


class ListRecentRequest(BaseModel):
    plant_id: str
    limit: int = 20
    connection_id: str | None = None


__all__ = ["ListForAssetRequest", "GetWorkOrderRequest", "ListRecentRequest"]
