"""Hermetic tests for McpDocSource (Sprint 6 WI4 / D16 / G29).

Drives McpDocSource through an in-process fastmcp stub host (mirrors the stubbing style in
test_mcp_toolbox.py). Asserts the adapter:
- calls document.list_by_type / document.get with the {"request": ...} envelope;
- maps each DocumentRef to the pipeline dict shape ({document_id, title, doc_type, excerpt});
- normalises a null excerpt to "" so the pipeline's body assembly never sees None;
- raises on an envelope error (the toolbox _require_ok contract).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastmcp import Client, FastMCP

from rca_agents.doc_source import McpDocSource

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


def _ok(data, connection_id=None):
    prov = {"tool_name": "x", "tool_version": "v1", "source": "sim",
            "connection_id": connection_id, "source_query": "q",
            "queried_at": REF.isoformat(), "response_id": "0190d3c9-0000-7000-8000-000000000abc",
            "record_count": len(data) if isinstance(data, list) else 1,
            "truncated": False, "raw_tags": [], "notes": None}
    return {"data": data, "provenance": prov, "error": None}


def _ref(document_id, title, doc_type, excerpt):
    return {"document_id": document_id, "asset_id": None, "title": title,
            "doc_type": doc_type, "uri": f"/docs/{document_id}",
            "last_modified": REF.isoformat(), "excerpt": excerpt}


@pytest.fixture
def stub_host() -> FastMCP:
    host = FastMCP("stub-document-host")

    @host.tool(name="document.list_by_type")
    async def list_by_type(request: dict):
        dt = request["doc_type"]
        rows = {
            "datasheet": [_ref("doc-ds-001", "Pump datasheet", "datasheet", "Flow 120 m3/h")],
            "rca_report": [_ref("doc-rca-001", "RCA Q1", "rca_report", None)],  # null excerpt
        }.get(dt, [])
        return _ok(rows, connection_id="refinery-gc.document.sp-main")

    @host.tool(name="document.get")
    async def get(request: dict):
        detail = {
            "doc-ds-001": _ref("doc-ds-001", "Pump datasheet", "datasheet", "Flow rate 120 m3/h"),
            "doc-rca-001": _ref("doc-rca-001", "RCA Q1", "rca_report", None),
        }[request["document_id"]]
        return _ok(detail, connection_id="refinery-gc.document.sp-main")

    @host.tool(name="document.get_fail")
    async def get_fail(request: dict):  # noqa: ARG001
        return {"data": None, "provenance": None,
                "error": {"code": "source_unavailable", "message": "boom", "retryable": True}}

    return host


@pytest.fixture
async def src(stub_host):
    async with Client(stub_host) as client:
        yield McpDocSource(client)


async def test_list_by_type_maps_to_pipeline_dicts(src):
    rows = await src.list_by_type("datasheet", "refinery-gc")
    assert rows == [{"document_id": "doc-ds-001", "title": "Pump datasheet",
                     "doc_type": "datasheet", "excerpt": "Flow 120 m3/h"}]


async def test_list_by_type_normalises_null_excerpt(src):
    rows = await src.list_by_type("rca_report", "refinery-gc")
    assert rows[0]["document_id"] == "doc-rca-001"
    assert rows[0]["excerpt"] == ""  # None -> "" so the pipeline body join never sees None


async def test_list_by_type_empty_for_unknown_type(src):
    assert await src.list_by_type("p_and_id", "refinery-gc") == []


async def test_get_returns_title_and_excerpt(src):
    doc = await src.get("doc-ds-001", "refinery-gc")
    assert doc["title"] == "Pump datasheet"
    assert doc["excerpt"] == "Flow rate 120 m3/h"


async def test_get_normalises_null_excerpt(src):
    doc = await src.get("doc-rca-001", "refinery-gc")
    assert doc["excerpt"] == ""


async def test_envelope_error_raises(stub_host):
    # A different McpDocSource method (get) hitting an erroring tool must raise, proving the
    # adapter enforces the same _require_ok contract as McpToolBox.
    class _ErrSource(McpDocSource):
        async def get(self, document_id: str, plant_id: str) -> dict:
            resp = await self._call("document.get_fail",
                                    {"document_id": document_id, "plant_id": plant_id})
            self._require_ok(resp, "document.get_fail")
            return {}

    async with Client(stub_host) as client:
        with pytest.raises(RuntimeError, match="source_unavailable"):
            await _ErrSource(client).get("doc-ds-001", "refinery-gc")
