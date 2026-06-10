"""S13.3 Maximo connector test: read + idempotent write-back, end-to-end through MCP.

Hermetic in-test Maximo OSLC fake with a mutable wonum-keyed store (upsert on POST,
so commit replays don't duplicate).
"""
import json
from uuid import uuid4

import httpx
from fastapi import Body, FastAPI, Request
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_maximo_mcp

ASSET = uuid4()
LOC = "CRDU-P101A"


def _build_maximo_fake():
    app = FastAPI(title="Maximo fake")
    # mutable store keyed by wonum (idempotent upsert), seeded with two WOs
    store: dict[str, dict] = {
        "WO-50012402": {"wonum": "WO-50012402", "location": LOC, "description": "seal leak",
                        "status": "COMP", "reportdate": "2026-03-28T19:00:00",
                        "wopriority": 1, "problemcode": "LEAK", "failurecode": "LEK"},
    }
    failreps = [{"failurenum": "FR-LEGACY-0001", "wonum": "WO-49900001", "location": LOC,
                 "failurecode": "SEAL-LEG-07", "reportdate": "2025-10-02T08:00:00"}]

    @app.get("/maxrest/oslc/os/mxwo")
    def get_mxwo(request: Request):
        return {"member": list(store.values()), "responseInfo": {"totalCount": len(store)}}

    @app.post("/maxrest/oslc/os/mxwo")
    def post_mxwo(record: dict = Body(...)):
        store[record["wonum"]] = {**store.get(record["wonum"], {}), **record}  # upsert
        return store[record["wonum"]]

    @app.get("/maxrest/oslc/os/mxfailrep")
    def get_mxfailrep(request: Request):
        return {"member": failreps, "responseInfo": {"totalCount": len(failreps)}}

    return app, store


def _parse_list(result) -> "ToolResponse[list[WorkOrder]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


def _parse_one(result) -> "ToolResponse[WorkOrder]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[WorkOrder].model_validate_json(json.dumps(payload))


async def test_maximo_read_and_idempotent_writeback():
    app, store = _build_maximo_fake()
    transport = httpx.ASGITransport(app=app)
    bindings = {(ASSET, "maximo"): SourceBinding(handle=LOC, raw_unit="n/a")}
    async with httpx.AsyncClient(transport=transport, base_url="http://maximo") as http:
        mcp = make_maximo_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            names = {t.name for t in await client.list_tools()}
            assert {"maximo.get_workorders", "maximo.get_failure_history",
                    "maximo.preview_writeback", "maximo.commit_writeback"} <= names

            # read work orders -> canonical, local-time -> UTC
            wos = _parse_list(await client.call_tool(
                "maximo.get_workorders", {"request": {"asset_id": str(ASSET)}}))
            assert wos.error is None and len(wos.data) == 1
            assert wos.data[0].work_order_id == "WO-50012402"
            assert wos.data[0].source_system == "maximo"
            assert wos.data[0].opened_at.tzinfo is not None

            # failure history surfaces the legacy code
            fh = _parse_list(await client.call_tool(
                "maximo.get_failure_history", {"request": {"asset_id": str(ASSET)}}))
            assert fh.data[0].failure_code == "SEAL-LEG-07"

            # preview does NOT write
            before = len(store)
            prev = _parse_one(await client.call_tool("maximo.preview_writeback", {"request": {
                "asset_id": str(ASSET), "wonum": "WO-99999001", "description": "new"}}))
            assert prev.error is None and prev.data.work_order_id == "WO-99999001"
            assert len(store) == before                     # nothing persisted

            # commit writes once; replay is idempotent
            payload = {"request": {"asset_id": str(ASSET), "wonum": "WO-99999001",
                                   "description": "new corrective", "priority": "1"}}
            c1 = _parse_one(await client.call_tool("maximo.commit_writeback", payload))
            assert c1.error is None and c1.data.work_order_id == "WO-99999001"
            after_first = len(store)
            await client.call_tool("maximo.commit_writeback", payload)   # replay
            assert len(store) == after_first                # no duplicate
            assert after_first == before + 1
