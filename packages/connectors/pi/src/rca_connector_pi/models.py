"""Request/response models for the tag + operator_log entity MCPs (Sprint 2b).

Every request is canonical_id-scoped and carries an optional connection_id (the router
disambiguates when a plant has more than one historian / operator-log connection). A request
NEVER carries a base_url — the connection registry owns endpoints, not the caller.
"""
from __future__ import annotations

from pydantic import AwareDatetime, BaseModel

from rca_contracts import HistorianMode


# ---- tag MCP ----

class GetHistoryRequest(BaseModel):
    canonical_id: str
    tag_name: str
    start: AwareDatetime
    end: AwareDatetime
    mode: HistorianMode = HistorianMode.stored
    connection_id: str | None = None


class GetCurrentRequest(BaseModel):
    canonical_id: str
    tag_name: str
    connection_id: str | None = None


class ListTagsRequest(BaseModel):
    canonical_id: str
    connection_id: str | None = None


class GetMetadataRequest(BaseModel):
    canonical_id: str
    tag_name: str
    connection_id: str | None = None


class TagInfo(BaseModel):
    """One point belonging to an asset (tag.list_for_asset)."""

    tag_name: str
    role: str | None
    engineering_units: str | None
    web_id: str
    descriptor: str | None


# ---- operator_log MCP ----

class ListLogsRequest(BaseModel):
    canonical_id: str
    start: AwareDatetime
    end: AwareDatetime
    connection_id: str | None = None


class GetLogRequest(BaseModel):
    log_id: str
    canonical_id: str
    connection_id: str | None = None


__all__ = [
    "GetHistoryRequest", "GetCurrentRequest", "ListTagsRequest", "GetMetadataRequest",
    "TagInfo", "ListLogsRequest", "GetLogRequest",
]
