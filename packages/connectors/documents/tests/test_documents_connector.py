"""Hermetic tests for the `document` entity MCP (Sprint 2b Track 3 Task 5).

Drives the FastAPI fake SharePoint/Graph surface via an ASGI transport so no real server is
needed. Asserts the tool set is the three document.* tools (+ test_connection) with NO
documents.* name, and that every response carries provenance.connection_id.
"""
from __future__ import annotations

import json

import httpx
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_contracts import DocumentRef, ToolResponse

from rca_connector_documents.server import make_document_mcp

from fake_documents import build_fake_documents

CANONICAL = "asset:refinery-gc:unit-101:p-101a"
PLANT = "refinery-gc"
CONNECTION_ID = "refinery-gc.document.sharepoint-main"


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id=PLANT, category="document",
            connector_type="sharepoint", base_url="http://docs-fake", extra_config={},
        ),
    ])


def _factory():
    app = build_fake_documents()
    transport = httpx.ASGITransport(app=app)

    def _make(base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, base_url="http://docs-fake")

    return _make


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


def _mcp():
    return make_document_mcp(router=_router(), http_client_factory=_factory())


async def test_document_tool_set_has_no_documents_prefix():
    async with Client(_mcp()) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {
        "document.search_for_asset", "document.get", "document.list_by_type",
        "test_connection",
    }
    assert not any(n.startswith("documents.") for n in names)


async def test_document_search_for_asset_returns_refs():
    async with Client(_mcp()) as client:
        # CanonicalSlugAssetGateway derives tag "P-101A"; query seeds /search with it.
        res = await client.call_tool("document.search_for_asset", {"request": {
            "canonical_id": CANONICAL, "top": 5,
        }})
        resp = _parse(res, list[DocumentRef])
    assert resp.error is None and resp.data is not None
    assert len(resp.data) >= 1
    by_id = {r.document_id: r for r in resp.data}
    assert "DS-P101A" in by_id
    assert by_id["DS-P101A"].doc_type == "datasheet"
    assert by_id["DS-P101A"].uri.endswith("DS-P101A")
    assert resp.provenance.record_count == len(resp.data)
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_document_get_by_id_returns_ref_with_excerpt():
    async with Client(_mcp()) as client:
        res = await client.call_tool("document.get", {"request": {
            "document_id": "RCA-2025-014", "plant_id": PLANT,
        }})
        resp = _parse(res, DocumentRef)
    assert resp.error is None and resp.data is not None
    assert resp.data.document_id == "RCA-2025-014"
    assert resp.data.doc_type == "rca_report"                # inferred from id prefix
    assert "mechanical seal" in (resp.data.excerpt or "")
    assert resp.provenance.connection_id == CONNECTION_ID


async def test_document_list_by_type_filters_to_requested_type():
    async with Client(_mcp()) as client:
        res = await client.call_tool("document.list_by_type", {"request": {
            "doc_type": "p_and_id", "plant_id": PLANT, "top": 20,
        }})
        resp = _parse(res, list[DocumentRef])
    assert resp.error is None and resp.data is not None
    assert len(resp.data) >= 1
    assert all(r.doc_type == "p_and_id" for r in resp.data)
    assert "PID-CRDU-01" in {r.document_id for r in resp.data}
    assert resp.provenance.connection_id == CONNECTION_ID
