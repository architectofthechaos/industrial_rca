"""S13.6 Documents connector test (hermetic): documents.search + documents.fetch through MCP."""
import json

import httpx
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastmcp import Client
from rca_contracts import DocumentRef, ToolResponse

from rca_connector_documents.server import make_documents_mcp

DRIVE = "refplant"


def _build_docs_fake() -> FastAPI:
    app = FastAPI(title="Docs fake")

    @app.get("/search")
    def search(q: str, top: int = 5):
        return {"value": [
            {"id": "DS-P101A", "name": "P-101A Datasheet", "asset": "P-101A",
             "docType": "datasheet", "score": 1.0, "webUrl": f"/drives/{DRIVE}/items/DS-P101A"},
            {"id": "RCA-2025-014", "name": "RCA seal failure", "asset": "P-101A",
             "docType": "rca_report", "score": 0.8, "webUrl": f"/drives/{DRIVE}/items/RCA-2025-014"},
        ]}

    @app.get(f"/drives/{DRIVE}/items/{{item_id}}")
    def item(item_id: str):
        return {"id": item_id, "name": f"{item_id}.pdf",
                "file": {"mimeType": "application/pdf"}, "scanned": False, "asset": "P-101A"}

    @app.get(f"/drives/{DRIVE}/items/{{item_id}}/content", response_class=PlainTextResponse)
    def content(item_id: str):
        return PlainTextResponse("mechanical seal flush plan; replace seal cartridge")

    return app


def _parse_list(result) -> "ToolResponse[list[DocumentRef]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[DocumentRef]].model_validate_json(json.dumps(payload))


def _parse_one(result) -> "ToolResponse[DocumentRef]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[DocumentRef].model_validate_json(json.dumps(payload))


async def test_search_and_fetch():
    transport = httpx.ASGITransport(app=_build_docs_fake())
    async with httpx.AsyncClient(transport=transport, base_url="http://docs") as http:
        mcp = make_documents_mcp(http_client=http)
        async with Client(mcp) as client:
            assert {"documents.search", "documents.fetch"} <= {t.name for t in await client.list_tools()}

            res = await client.call_tool(
                "documents.search", {"request": {"query": "mechanical seal", "top": 3}})
            search = _parse_list(res)
            assert search.error is None and len(search.data) == 2
            assert search.data[0].document_id == "DS-P101A"
            assert search.data[0].doc_type == "datasheet"
            assert search.data[0].uri.endswith("DS-P101A")
            assert search.provenance.record_count == 2

            res2 = await client.call_tool(
                "documents.fetch", {"request": {"document_id": "RCA-2025-014"}})
            doc = _parse_one(res2)
            assert doc.error is None
            assert doc.data.document_id == "RCA-2025-014"
            assert doc.data.doc_type == "rca_report"          # inferred from id prefix
            assert "mechanical seal" in (doc.data.excerpt or "")
