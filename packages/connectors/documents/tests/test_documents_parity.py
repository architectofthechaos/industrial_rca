"""S13.8 parity: Documents connector against the REAL EPIC-002 docs simulator (HTTP).

Default http://127.0.0.1:8004; never imports rca_simulator. Skips when sim is down.
Run with: `task parity:documents`.
"""
import json
import os

import httpx
import pytest
from fastmcp import Client
from rca_contracts import DocumentRef, ToolResponse

from rca_connector_documents.server import make_documents_mcp

DOCS_SIM_URL = os.environ.get("DOCS_SIM_URL", "http://127.0.0.1:8004")


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{DOCS_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(), reason=f"Docs simulator not reachable at {DOCS_SIM_URL} (run `task parity:documents`)"
)


def _parse_list(result) -> "ToolResponse[list[DocumentRef]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[DocumentRef]].model_validate_json(json.dumps(payload))


def _parse_one(result) -> "ToolResponse[DocumentRef]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[DocumentRef].model_validate_json(json.dumps(payload))


async def test_search_and_fetch_against_real_simulator():
    async with httpx.AsyncClient(base_url=DOCS_SIM_URL) as http:
        mcp = make_documents_mcp(http_client=http)
        async with Client(mcp) as client:
            res = await client.call_tool(
                "documents.search", {"request": {"query": "mechanical seal flush", "top": 3}})
            search = _parse_list(res)
            assert search.error is None and len(search.data) > 0
            top = search.data[0]
            assert top.doc_type in {"datasheet", "p_and_id", "rca_report", "soop", "manual", "other"}
            assert search.provenance.record_count == len(search.data)

            res2 = await client.call_tool(
                "documents.fetch", {"request": {"document_id": top.document_id}})
            doc = _parse_one(res2)
            assert doc.error is None and doc.data.document_id == top.document_id
            assert doc.data.excerpt   # fetched real content
