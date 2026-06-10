"""Documents connector tools (S13.6): documents.search + documents.fetch (SharePoint/HTTP backend).

Query/document-scoped (no signal/asset), so the orchestrator resolves no source binding.
The S3/MinIO backend lives in s3_backend.py behind the same DocumentRef contract.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from rca_connector_sdk import MalformedResponse, evidence_tool
from rca_contracts import DocType, DocumentRef

DRIVE = "refplant"   # the sim's drive id; would be per-deployment config in production

_DOCTYPE = {"datasheet": "datasheet", "pid": "p_and_id", "rca_report": "rca_report"}
_ID_PREFIX = {"DS": "datasheet", "PID": "p_and_id", "RCA": "rca_report"}


def _doc_type(source_value: str | None, doc_id: str) -> DocType:
    """Unified mapping used by BOTH search and fetch: prefer the source docType, then the
    id prefix, then 'other' — so the same document gets the same doc_type either way."""
    mapped = _DOCTYPE.get(source_value or "")
    if mapped:
        return mapped  # type: ignore[return-value]
    return _ID_PREFIX.get(doc_id.split("-", 1)[0], "other")  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SearchRequest(BaseModel):
    query: str
    top: int = 5


class FetchRequest(BaseModel):
    document_id: str


@evidence_tool(name="documents.search", version="0.1.0", source="documents",
               request=SearchRequest, response=list[DocumentRef])
class DocumentsSearch:
    async def fetch(self, ctx, req: SearchRequest):
        resp = await ctx.http.get("/search", params={"q": req.query, "top": req.top})
        resp.raise_for_status()
        hits = resp.json().get("value") or []
        # query is captured in source_query (the URL); no raw source tags for a search
        ctx.prov.record(source_query=str(resp.request.url), raw_tags=[], record_count=len(hits))
        return hits

    def translate(self, ctx, raw) -> list[DocumentRef]:
        out: list[DocumentRef] = []
        for h in raw:
            if not isinstance(h, dict):
                continue                                  # skip null/garbage entries
            doc_id = h.get("id")
            if not doc_id:
                continue                                  # best-effort ranking: drop hits w/o id
            out.append(DocumentRef(
                document_id=doc_id,
                asset_id=None,                            # tag->AssetID needs MAR (later)
                title=str(h.get("name") or doc_id),
                doc_type=_doc_type(h.get("docType"), doc_id),
                uri=h.get("webUrl") or f"/drives/{DRIVE}/items/{doc_id}",
                last_modified=_now(),                     # sim search hits carry no mtime
                excerpt=None,
            ))
        return out


@evidence_tool(name="documents.fetch", version="0.1.0", source="documents",
               request=FetchRequest, response=DocumentRef)
class DocumentsFetch:
    async def fetch(self, ctx, req: FetchRequest):
        item = await ctx.http.get(f"/drives/{DRIVE}/items/{req.document_id}")
        item.raise_for_status()
        content = await ctx.http.get(f"/drives/{DRIVE}/items/{req.document_id}/content")
        content.raise_for_status()
        ctx.prov.record(source_query=str(item.request.url),
                        raw_tags=[req.document_id], record_count=1)
        return {"meta": item.json(), "content": content.text}

    def translate(self, ctx, raw) -> DocumentRef:
        meta = raw.get("meta") if isinstance(raw, dict) else None
        if not isinstance(meta, dict) or not meta.get("id"):
            raise MalformedResponse("document fetch response missing item metadata / id")
        doc_id = meta["id"]
        text = raw.get("content") or ""
        return DocumentRef(
            document_id=doc_id,
            asset_id=None,
            title=str(meta.get("name") or doc_id),
            doc_type=_doc_type(meta.get("docType"), doc_id),
            uri=f"/drives/{DRIVE}/items/{doc_id}",
            last_modified=_now(),
            excerpt=text[:1000] or None,                  # empty content -> None, not ""
        )


__all__ = ["SearchRequest", "FetchRequest", "DocumentsSearch", "DocumentsFetch"]
