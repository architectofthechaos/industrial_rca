"""S13.8 parity test: Maximo connector against the REAL EPIC-002 Maximo simulator.

Talks over HTTP (default http://127.0.0.1:8002); never imports rca_simulator.
Skips when the sim isn't running. Run with: `task parity:maximo`.
"""
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_maximo.server import make_maximo_mcp

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
ASSET = uuid4()
LOC = "CRDU-P101A"   # P-101A's maximo_location in the reference fixture


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{MAXIMO_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(),
    reason=f"Maximo simulator not reachable at {MAXIMO_SIM_URL} (run `task parity:maximo`)",
)


def _parse_list(result) -> "ToolResponse[list[WorkOrder]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def test_read_and_idempotent_writeback_against_real_simulator():
    bindings = {(ASSET, "maximo"): SourceBinding(handle=LOC, raw_unit="n/a")}
    async with httpx.AsyncClient(base_url=MAXIMO_SIM_URL) as http:
        mcp = make_maximo_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            wos = _parse_list(await client.call_tool(
                "maximo.get_workorders", {"request": {"asset_id": str(ASSET)}}))
            assert wos.error is None and len(wos.data) > 0
            wonums = {w.work_order_id for w in wos.data}
            assert {"WO-50012345", "WO-50012402"} <= wonums       # seal-leak scenario WOs
            assert all(w.source_system == "maximo" for w in wos.data)
            assert all(w.opened_at.tzinfo is not None for w in wos.data)

            # idempotent write-back against the real sim. Unique wonum so the test is
            # run-independent even against a reused sim.
            async def count() -> int:
                return len(_parse_list(await client.call_tool(
                    "maximo.get_workorders", {"request": {"asset_id": str(ASSET)}})).data)

            wonum = f"WO-PARITY-{uuid4().hex[:8]}"
            payload = {"request": {"asset_id": str(ASSET), "wonum": wonum,
                                   "description": "parity write", "priority": "3"}}
            c0 = await count()
            await client.call_tool("maximo.commit_writeback", payload)
            c1 = await count()
            await client.call_tool("maximo.commit_writeback", payload)   # replay
            c2 = await count()
            assert c1 == c0 + 1                                          # first commit adds one
            assert c2 == c1                                              # replay is idempotent
