import inspect
from datetime import datetime, timezone
import pytest
from fastmcp import Client, FastMCP
from rca_agents.mcp_toolbox import McpToolBox
from rca_agents.toolbox import ToolBox

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
CID = "asset:refinery-gc:unit-101:p-101a"


def _ok(data, connection_id=None):
    prov = {"tool_name": "x", "tool_version": "v1", "source": "sim",
            "connection_id": connection_id, "source_query": "q",
            "queried_at": REF.isoformat(), "response_id": "0190d3c9-0000-7000-8000-000000000abc",
            "record_count": len(data) if isinstance(data, list) else 1,
            "truncated": False, "raw_tags": [], "notes": None}
    return {"data": data, "provenance": prov, "error": None}


@pytest.fixture
def stub_host() -> FastMCP:
    host = FastMCP("stub-entity-host")

    @host.tool(name="tag.list_for_asset")
    async def list_tags(request: dict):
        return _ok([{"tag_name": "P-101A.vibration_radial", "role": "vibration_radial"}],
                   connection_id="refinery-gc.historian.pi-main")

    @host.tool(name="tag.get_history")
    async def hist(request: dict):
        # Three points: mean≈2.87, max=6.6, ratio≈2.3 → critical under the pure ratio rule
        return _ok({"tag": {"tag_name": request["tag_name"]},
                    "values": [{"value": 1.0}, {"value": 1.0}, {"value": 6.6}]},
                   connection_id="refinery-gc.historian.pi-main")

    @host.tool(name="work_order.list_for_asset")
    async def wos(request: dict):
        return _ok([{"work_order_id": "WO-50012402", "description": "seal leak",
                     "status": "WAPPR", "priority": "1", "failure_code": "LEK",
                     "opened_at": "2026-03-28T00:00:00+00:00"}],
                   connection_id="refinery-gc.cmms.maximo-main")

    @host.tool(name="document.search_for_asset")
    async def docs(request: dict):
        return _ok([{"document_id": "RCA-2025-014", "title": "prior seal RCA",
                     "doc_type": "rca_report", "excerpt": "dry-running seal face"}],
                   connection_id="refinery-gc.document.sp-main")

    @host.tool(name="operator_log.list_for_asset")
    async def logs(request: dict):
        return _ok([{"message": "slight whine", "timestamp": "2026-03-06T00:00:00+00:00",
                     "tag_name": "P-101A"}],
                   connection_id="refinery-gc.operator_log.pi-main")

    @host.tool(name="asset.get")
    async def aget(request: dict):
        return _ok({"canonical_id": CID, "tag": "P-101A", "service": "charge pump",
                    "iso14224_class": "pump.centrifugal", "iso14224_class_kg": "equipment-class:bb1"})

    @host.tool(name="asset.search")
    async def asearch(request: dict):
        return _ok([{"canonical_id": CID, "tag": "P-101A"}])

    @host.tool(name="kg.get_asset_context")
    async def kgctx(request: dict):
        return _ok({"kg_warm": False, "asset": {"id": CID, "name": "P-101A"},
                    "iso14224_class": request.get("iso14224_class"),
                    "applicable_failure_modes": [{"code": "ELP", "id": "failure-mode:elp",
                                                  "name": "External leakage"}],
                    "prior_events_on_asset": [], "prior_events_for_class_at_plant": []})

    @host.tool(name="kg.upsert_asset")
    async def upsert(request: dict):
        return _ok({"canonical_id": request["canonical_id"], "created": True})

    @host.tool(name="kg.link_failure_mode")
    async def link(request: dict):
        return _ok({"canonical_id": request["canonical_id"],
                    "failure_mode_code": request["failure_mode_code"], "linked": True})

    return host


@pytest.fixture
async def tb(stub_host):
    async with Client(stub_host) as client:
        yield McpToolBox(client)


_PROTOCOL_METHODS = {
    "search_assets",
    "asset_summary",
    "get_asset_context",
    "failure_modes_for_class",
    "tag_history",
    "work_orders_for_asset",
    "documents_for_asset",
    "operator_logs_for_asset",
    "upsert_asset",
    "link_failure_mode",
}


def test_satisfies_protocol(tb):
    # ToolBox is a plain (non-runtime_checkable) Protocol, so isinstance() raises; assert the
    # structural contract instead: every Protocol method exists on McpToolBox as a coroutine fn.
    methods = [n for n in dir(ToolBox) if not n.startswith("_")]
    assert set(methods) == _PROTOCOL_METHODS
    for name in _PROTOCOL_METHODS:
        fn = getattr(tb, name, None)
        assert fn is not None and inspect.iscoroutinefunction(fn), name


async def test_tag_history_fans_out_and_summarizes(tb):
    tags, prov = await tb.tag_history(CID, reference_time=REF, lookback_hours=720)
    assert tags[0]["tag_name"] == "P-101A.vibration_radial"
    assert tags[0]["role"] == "vibration_radial"
    assert tags[0]["max"] == 6.6 and tags[0]["severity"] == "critical"
    assert prov.connection_id == "refinery-gc.historian.pi-main"
    assert prov.section == "tag" and prov.record_count == 1


async def test_operator_logs_renamed(tb):
    logs, prov = await tb.operator_logs_for_asset(CID, reference_time=REF, lookback_hours=720)
    assert logs[0]["text"] == "slight whine" and logs[0]["at"] == "2026-03-06T00:00:00+00:00"
    assert prov.connection_id == "refinery-gc.operator_log.pi-main"


async def test_get_asset_context_bridges_mar_class(tb):
    ctx = await tb.get_asset_context(CID)
    assert ctx["iso14224_class"] == "equipment-class:bb1"
    assert ctx["applicable_failure_modes"][0]["code"] == "ELP"


async def test_upsert_and_link_return_bools(tb):
    assert await tb.upsert_asset(canonical_id=CID, name="P-101A",
                                 iso14224_class="equipment-class:bb1", confidence=0.95,
                                 method="register", reference_time=REF) is True
    assert await tb.link_failure_mode(canonical_id=CID, failure_mode_code="ELP") is True


async def test_work_orders_and_documents_passthrough(tb):
    wos, p1 = await tb.work_orders_for_asset(CID)
    assert wos[0]["work_order_id"] == "WO-50012402" and p1.connection_id
    docs, p2 = await tb.documents_for_asset(CID, "seal leak")
    assert docs[0]["document_id"] == "RCA-2025-014" and p2.connection_id
