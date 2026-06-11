"""The ``document`` entity MCP — canonical DocumentRefs, SharePoint-sim-backed (Sprint 2b Track 3).

Hand-wired in the tag/operator_log idiom (explicit ToolResponse via ok_response +
map_source_error), NOT @evidence_tool: base_url arrives per-request via the connection
router (resolved from the request's plant + optional connection_id), so each call opens its
own httpx client. Every response carries provenance.connection_id (2b acceptance #12). NO
``documents.*`` tool name exists.

Tools:
* document.search_for_asset{canonical_id, query?, top} -> list[DocumentRef]
* document.get{document_id, plant_id} -> DocumentRef
* document.list_by_type{doc_type, plant_id, top} -> list[DocumentRef]

The DocumentRef translation (search hit / drive item -> canonical DocumentRef) and the
doc_type inference are reused verbatim from the old documents connector. document is
query-scoped: it needs the asset *tag* (AssetGateway.tag_for) to seed the search, never a
source_handle — so the default CanonicalSlugAssetGateway works out of the box.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from fastmcp import FastMCP
from rca_connector_sdk import (
    AssetGateway,
    CanonicalSlugAssetGateway,
    ConnectionRouter,
    MalformedResponse,
    build_server,
    map_source_error,
    ok_response,
    register_health,
)
from rca_contracts import DocType, DocumentRef, ToolResponse, parse_canonical_id

from .health import DocumentHealthProbe
from .models import GetDocumentRequest, ListByTypeRequest, SearchForAssetRequest

_VERSION = "0.1.0"
_SOURCE = "sharepoint"
_CAT_DOCUMENT = "document"

DRIVE = "refplant"   # TODO(track1): source the drive id from ConnectionInfo.extra_config

_DOCTYPE = {"datasheet": "datasheet", "pid": "p_and_id", "rca_report": "rca_report"}
_ID_PREFIX = {"DS": "datasheet", "PID": "p_and_id", "RCA": "rca_report"}

HttpClientFactory = Callable[[str], httpx.AsyncClient]


def _default_http_factory(base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=30.0)


def _doc_type(source_value: str | None, doc_id: str) -> DocType:
    """Unified mapping used by every tool: prefer the source docType, then the id prefix,
    then 'other' — so the same document gets the same doc_type regardless of how it arrived."""
    mapped = _DOCTYPE.get(source_value or "")
    if mapped:
        return mapped  # type: ignore[return-value]
    return _ID_PREFIX.get(doc_id.split("-", 1)[0], "other")  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hit_to_ref(h: dict) -> DocumentRef | None:
    """One search hit -> DocumentRef (reused from the old documents.search translate)."""
    doc_id = h.get("id")
    if not doc_id:
        return None                                   # best-effort ranking: drop hits w/o id
    return DocumentRef(
        document_id=doc_id,
        asset_id=None,                                # tag->AssetID needs MAR (later)
        title=str(h.get("name") or doc_id),
        doc_type=_doc_type(h.get("docType"), doc_id),
        uri=h.get("webUrl") or f"/drives/{DRIVE}/items/{doc_id}",
        last_modified=_now(),                         # sim search hits carry no mtime
        excerpt=None,
    )


def make_document_mcp(
    *,
    router: ConnectionRouter,
    assets: AssetGateway | None = None,
    http_client_factory: HttpClientFactory | None = None,
    default_base_url: str | None = None,
) -> FastMCP:
    # document is query-scoped: only tag_for is needed (to seed the search), so the default
    # CanonicalSlugAssetGateway works without any binding.
    gateway = assets or CanonicalSlugAssetGateway()
    factory = http_client_factory or _default_http_factory
    mcp = build_server("document")
    register_health(
        mcp, version=_VERSION,
        probe=DocumentHealthProbe(default_base_url=default_base_url),
    )

    @mcp.tool(name="document.search_for_asset")
    async def search_for_asset(
        request: SearchForAssetRequest,
    ) -> ToolResponse[list[DocumentRef]]:
        envelope = ToolResponse[list[DocumentRef]]
        try:
            plant_id = parse_canonical_id(request.canonical_id).plant_id
            conn = await router.active(plant_id, _CAT_DOCUMENT, request.connection_id)
            tag = await gateway.tag_for(request.canonical_id)
            query = f"{tag} {request.query}".strip() if request.query else tag
            async with factory(conn.base_url) as client:
                resp = await client.get("/search", params={"q": query, "top": request.top})
                resp.raise_for_status()
                hits = resp.json().get("value") or []
            refs = [ref for h in hits if isinstance(h, dict) and (ref := _hit_to_ref(h))]
            return ok_response(
                refs, tool="document.search_for_asset", version=_VERSION,
                source=_SOURCE, source_query=str(resp.request.url),
                record_count=len(refs), raw_tags=[tag],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="document.get")
    async def get(request: GetDocumentRequest) -> ToolResponse[DocumentRef]:
        envelope = ToolResponse[DocumentRef]
        try:
            conn = await router.active(request.plant_id, _CAT_DOCUMENT, request.connection_id)
            async with factory(conn.base_url) as client:
                item = await client.get(f"/drives/{DRIVE}/items/{request.document_id}")
                item.raise_for_status()
                content = await client.get(
                    f"/drives/{DRIVE}/items/{request.document_id}/content"
                )
                content.raise_for_status()
                meta = item.json()
                text = content.text
            if not isinstance(meta, dict) or not meta.get("id"):
                raise MalformedResponse("document fetch response missing item metadata / id")
            doc_id = meta["id"]
            ref = DocumentRef(
                document_id=doc_id,
                asset_id=None,
                title=str(meta.get("name") or doc_id),
                doc_type=_doc_type(meta.get("docType"), doc_id),
                uri=f"/drives/{DRIVE}/items/{doc_id}",
                last_modified=_now(),
                excerpt=text[:1000] or None,           # empty content -> None, not ""
            )
            return ok_response(
                ref, tool="document.get", version=_VERSION,
                source=_SOURCE, source_query=str(item.request.url),
                record_count=1, raw_tags=[request.document_id],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    @mcp.tool(name="document.list_by_type")
    async def list_by_type(request: ListByTypeRequest) -> ToolResponse[list[DocumentRef]]:
        envelope = ToolResponse[list[DocumentRef]]
        try:
            conn = await router.active(request.plant_id, _CAT_DOCUMENT, request.connection_id)
            async with factory(conn.base_url) as client:
                # The sim has no by-type endpoint: search broadly (wildcard) then filter by
                # doc_type client-side (LIMITATION: not pushed down to the source). top is
                # applied AFTER the filter so callers get up to `top` of the requested type.
                resp = await client.get("/search", params={"q": "*", "top": 1000})
                resp.raise_for_status()
                hits = resp.json().get("value") or []
            refs = [ref for h in hits if isinstance(h, dict) and (ref := _hit_to_ref(h))]
            filtered = [r for r in refs if r.doc_type == request.doc_type][: max(request.top, 0)]
            return ok_response(
                filtered, tool="document.list_by_type", version=_VERSION,
                source=_SOURCE, source_query=str(resp.request.url),
                record_count=len(filtered),
                raw_tags=[r.document_id for r in filtered],
                connection_id=conn.connection_id,
            )
        except Exception as exc:  # noqa: BLE001
            return envelope.fail(map_source_error(exc))

    return mcp


__all__ = ["make_document_mcp"]
