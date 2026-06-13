"""Live acceptance test: MarAssetGateway resolves CMMS work-order evidence (Sprint 6 WI1 / D13).

Calls ``work_order.list_for_asset`` against the running HTTP host (which uses
MarAssetGateway for the CMMS mount) and asserts that at least one work-order record
is returned for the reference pump P-101A.

Stack-gated: needs ``task probe:host`` (dynamic router + Maximo sim) + Postgres MAR
seeded with the P-101A CMMS alias. No LLM keys required (a single MCP tool call).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RCA_STACK") != "1",
    reason="requires the live HTTP host + Maximo sim + MAR seeded with CMMS alias",
)

CID = "asset:refinery-gc:unit-101:p-101a"
HOST_URL = os.environ.get("MCP_HOST_URL", "http://127.0.0.1:8100/mcp")


@pytest.mark.asyncio
async def test_work_order_list_resolves_via_mar():
    """MarAssetGateway resolves canonical_id -> CMMS handle -> Maximo work orders."""
    from fastmcp import Client

    async with Client(HOST_URL) as client:
        res = await client.call_tool(
            "work_order.list_for_asset", {"request": {"canonical_id": CID}})
        sc = res.structured_content or {}
        err = sc.get("error")
        assert err is None, f"unexpected error from work_order.list_for_asset: {err}"
        prov = sc.get("provenance") or {}
        record_count = prov.get("record_count", 0)
        assert record_count > 0, (
            f"expected at least one work order for {CID} via MAR-backed gateway; "
            f"got record_count={record_count}  data={sc.get('data')}"
        )
