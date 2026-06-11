"""Live parity test: the `document` MCP against the REAL docs simulator (:8004).

Talks over HTTP (default http://127.0.0.1:8004); never imports rca_simulator. Skips when
the sim isn't running. Run with: `task parity:documents`.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import ConnectionInfo, StaticConnectionRouter
from rca_contracts import DocumentRef, ToolResponse

from rca_connector_documents.server import make_document_mcp

DOCS_SIM_URL = os.environ.get("DOCS_SIM_URL", "http://127.0.0.1:8004")
CANONICAL = "asset:refinery-gc:unit-101:p-101a"
PLANT = "refinery-gc"
CONNECTION_ID = "refinery-gc.document.sharepoint-main"


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{DOCS_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Docs simulator not reachable at {DOCS_SIM_URL} (run `task parity:documents`)",
)


def _router() -> StaticConnectionRouter:
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=CONNECTION_ID, plant_id=PLANT, category="document",
            connector_type="sharepoint", base_url=DOCS_SIM_URL, extra_config={},
        ),
    ])


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


async def test_search_get_and_list_by_type_against_real_simulator():
    mcp = make_document_mcp(router=_router())
    async with Client(mcp) as client:
        # search_for_asset seeds the query with the asset tag (P-101A) + extra terms
        search = _parse(await client.call_tool("document.search_for_asset", {"request": {
            "canonical_id": CANONICAL, "query": "mechanical seal flush", "top": 5,
        }}), list[DocumentRef])
        assert search.error is None and search.data is not None and len(search.data) > 0
        top = search.data[0]
        assert top.doc_type in {
            "datasheet", "p_and_id", "rca_report", "soop", "manual", "other"
        }
        assert search.provenance.record_count == len(search.data)
        assert search.provenance.connection_id == CONNECTION_ID

        doc = _parse(await client.call_tool("document.get", {"request": {
            "document_id": top.document_id, "plant_id": PLANT,
        }}), DocumentRef)
        assert doc.error is None and doc.data.document_id == top.document_id
        assert doc.data.excerpt   # fetched real content
        assert doc.provenance.connection_id == CONNECTION_ID

        by_type = _parse(await client.call_tool("document.list_by_type", {"request": {
            "doc_type": top.doc_type, "plant_id": PLANT, "top": 20,
        }}), list[DocumentRef])
    assert by_type.error is None and by_type.data is not None
    assert all(r.doc_type == top.doc_type for r in by_type.data)
    assert by_type.provenance.connection_id == CONNECTION_ID
