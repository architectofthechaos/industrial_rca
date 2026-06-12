from datetime import datetime, timezone

import pytest
from fastmcp import Client, FastMCP
from rca_agents.wo import McpWorkOrderCreator

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def host():
    h = FastMCP("wo-stub")

    @h.tool(name="work_order.create")
    async def create(request: dict):
        return {"data": {"work_order_id": "WO-RCA-0001", "status": "WAPPR",
                         "description": request["description"]},
                "provenance": {"tool_name": "work_order.create", "tool_version": "v1",
                               "source": "maximo", "connection_id": "refinery-gc.cmms.maximo-main",
                               "source_query": "create", "queried_at": REF.isoformat(),
                               "response_id": "0190d3c9-0000-7000-8000-0000000000ee",
                               "record_count": 1, "truncated": False, "raw_tags": [], "notes": None},
                "error": None}
    return h


async def test_create_returns_work_order_dict(host):
    async with Client(host) as client:
        wo = McpWorkOrderCreator(client)
        out = await wo.create(canonical_id="asset:r:u:p-101a", description="replace seal",
                              priority="immediate", work_type="CM",
                              references={"probe_run_id": "p1", "conclusion_id": "c1"},
                              requested_by="agent", reported_at=REF)
    assert out["work_order_id"] == "WO-RCA-0001"
