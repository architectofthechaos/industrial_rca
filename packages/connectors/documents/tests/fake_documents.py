"""A small FastAPI fake of the SharePoint/Graph document surface for the document MCP tests.

Serves the routes the document tools call: GET /search (returns ranked hits with a docType),
GET /drives/{drive}/items/{id} (metadata) and .../content (body text), plus /openapi.json via
FastAPI. Hermetic: the product test venv never imports rca_simulator — the connector talks
REST exactly as it would to a real SharePoint/Graph backend.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

DRIVE = "refplant"

# Docs spanning several doc_types so list_by_type filtering is testable. All asset P-101A.
_DOCS: dict[str, dict[str, Any]] = {
    "DS-P101A": {"id": "DS-P101A", "name": "P-101A Datasheet", "asset": "P-101A",
                 "docType": "datasheet"},
    "PID-CRDU-01": {"id": "PID-CRDU-01", "name": "CRDU P&ID", "asset": "P-101A",
                    "docType": "pid"},
    "RCA-2025-014": {"id": "RCA-2025-014", "name": "RCA seal failure", "asset": "P-101A",
                     "docType": "rca_report"},
}
_CONTENT = {
    "DS-P101A": "centrifugal pump datasheet; mechanical seal; design flow 120 m3/h",
    "PID-CRDU-01": "piping and instrumentation diagram for the crude unit",
    "RCA-2025-014": "mechanical seal flush plan; replace seal cartridge; root cause analysis",
}


def build_fake_documents() -> FastAPI:
    app = FastAPI(title="SharePoint/Graph Document Simulator", version="1.0.0")

    @app.get("/search")
    def search(q: str, top: int = 5) -> dict[str, Any]:
        # Naive relevance: a doc matches if any query token is in its name (or q is the
        # wildcard "*" used by list_by_type). Ordered by id for determinism.
        tokens = [t.lower() for t in q.split() if t and t != "*"]
        hits = []
        for doc in _DOCS.values():
            hay = f"{doc['name']} {doc['asset']}".lower()
            if not tokens or any(tok in hay for tok in tokens):
                hits.append({**doc, "score": 1.0,
                             "webUrl": f"/drives/{DRIVE}/items/{doc['id']}"})
        hits.sort(key=lambda h: h["id"])
        return {"value": hits[:top]}

    @app.get(f"/drives/{DRIVE}/items/{{item_id}}")
    def item(item_id: str) -> dict[str, Any]:
        doc = _DOCS.get(item_id, {"id": item_id, "name": f"{item_id}", "docType": None})
        return {"id": doc["id"], "name": f"{doc['name']}.pdf", "docType": doc.get("docType"),
                "file": {"mimeType": "application/pdf"}, "scanned": False, "asset": "P-101A"}

    @app.get(f"/drives/{DRIVE}/items/{{item_id}}/content", response_class=PlainTextResponse)
    def content(item_id: str) -> PlainTextResponse:
        return PlainTextResponse(_CONTENT.get(item_id, ""))

    return app


__all__ = ["build_fake_documents", "DRIVE"]
