"""S2.6 — SharePoint / Graph document simulator (FastAPI).

Serves the fixture documents over two surfaces the documents connector calls:
a SharePoint-style search (``GET /search``) and Graph drive-item metadata +
content (``/drives/{drive}/items/{item}``). Scanned documents are served with
injected OCR noise. The search shape is simplified (the connector owns the real
Graph contract); ranking comes from the BM25 + lexical index.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from .search_index import DocumentIndex, load_documents, ocr_noise, seed_from_id

_DRIVE = "refplant"


def create_app(docs_dir: str | Path) -> FastAPI:
    documents = load_documents(docs_dir)
    by_id = {d.doc_id: d for d in documents}
    index = DocumentIndex(documents)
    app = FastAPI(title="SharePoint/Graph Document Simulator")

    @app.get("/search")
    def search(q: str, top: int = 5):
        hits = index.search(q, top_k=top)
        return {"value": [
            {
                "id": r.document.doc_id,
                "name": r.document.title,
                "asset": r.document.asset,
                "docType": r.document.doc_type,
                "score": r.score,
                "webUrl": f"/drives/{_DRIVE}/items/{r.document.doc_id}",
            }
            for r in hits
        ]}

    @app.get("/drives/{drive}/items/{item_id}")
    def drive_item(drive: str, item_id: str):
        doc = by_id.get(item_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="item not found")
        size = len(doc.text.encode("utf-8"))
        return {
            "id": doc.doc_id,
            "name": f"{doc.title}.pdf",
            "size": size,
            "file": {"mimeType": "application/pdf"},
            "scanned": doc.scanned,
            "asset": doc.asset,
        }

    @app.get("/drives/{drive}/items/{item_id}/content", response_class=PlainTextResponse)
    def drive_item_content(drive: str, item_id: str):
        doc = by_id.get(item_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="item not found")
        text = doc.text
        if doc.scanned:
            text = ocr_noise(text, seed=seed_from_id(doc.doc_id))
        return PlainTextResponse(text)

    return app


def build_default_app() -> FastAPI:
    import os
    return create_app(os.environ.get("DOCS_PATH", "fixtures/refplant/documents"))


__all__ = ["create_app", "build_default_app"]
