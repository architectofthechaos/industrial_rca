"""Request models for the document entity MCP (Sprint 2b Track 3 Task 5).

search_for_asset is canonical_id-scoped (the asset tag seeds the search query). get /
list_by_type take a vendor document id / plant_id directly — a payload-level vendor id is
allowed where there is no canonical_id. No request ever carries a base_url: the connection
registry owns endpoints.
"""
from __future__ import annotations

from pydantic import BaseModel

from rca_contracts import DocType


class SearchForAssetRequest(BaseModel):
    canonical_id: str
    query: str | None = None
    top: int = 5
    connection_id: str | None = None


class GetDocumentRequest(BaseModel):
    document_id: str            # vendor id, allowed at payload level
    plant_id: str               # needed for routing (no canonical_id to derive it)
    connection_id: str | None = None


class ListByTypeRequest(BaseModel):
    doc_type: DocType
    plant_id: str
    top: int = 20
    connection_id: str | None = None


__all__ = ["SearchForAssetRequest", "GetDocumentRequest", "ListByTypeRequest"]
