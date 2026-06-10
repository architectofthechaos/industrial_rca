"""S13.8 parity test: SAP PM connector against the REAL EPIC-002 SAP simulator.

Talks over HTTP (default http://127.0.0.1:8003); never imports rca_simulator.
Skips when the sim isn't running. Run with: `task parity:sap`.
"""
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_sap_pm.server import make_sap_mcp

SAP_SIM_URL = os.environ.get("SAP_SIM_URL", "http://127.0.0.1:8003")
ASSET = uuid4()
EQUNR = "10001234"   # P-101A's sap_equipment in the reference fixture


def _sim_reachable() -> bool:
    try:
        return httpx.get(f"{SAP_SIM_URL}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(), reason=f"SAP simulator not reachable at {SAP_SIM_URL} (run `task parity:sap`)"
)


def _parse(result) -> "ToolResponse[list[WorkOrder]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def test_get_notifications_against_real_simulator():
    bindings = {(ASSET, "sap_pm"): SourceBinding(handle=EQUNR, raw_unit="n/a")}
    async with httpx.AsyncClient(base_url=SAP_SIM_URL) as http:
        mcp = make_sap_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            res = await client.call_tool(
                "sap_pm.get_notifications", {"request": {"asset_id": str(ASSET)}}
            )
            resp = _parse(res)
            assert resp.error is None, resp.error
            assert resp.data is not None and len(resp.data) > 0
            wo = resp.data[0]
            assert wo.source_system == "sap_pm"
            assert wo.opened_at.tzinfo is not None
            assert str(wo.asset_id) == str(ASSET)
            assert resp.provenance.record_count == len(resp.data)
