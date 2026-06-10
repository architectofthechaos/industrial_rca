"""S13.8 cross-source parity: SAP PM and Maximo unify under the canonical WorkOrder.

Proves the central promise of the connector layer — that two different CMMS sources,
talking different protocols (SAP OData v2 vs Maximo OSLC) with different identifiers
(EQUNR `10001234` vs location `CRDU-P101A`) and different code schemes (SAP FECOD vs
Maximo failurecode) — both translate to the SAME canonical `WorkOrder` shape for the
SAME logical asset (P-101A), and converge on the SAME ISO-14224 failure code (`LEK`)
for the seal-leak event that appears in both systems.

Requires BOTH the Maximo (:8002) and SAP (:8003) simulators; skips otherwise. Talks
only HTTP — never imports rca_simulator. Run with: `task parity:cross`.
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
from rca_connector_sap_pm.server import make_sap_mcp

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
SAP_SIM_URL = os.environ.get("SAP_SIM_URL", "http://127.0.0.1:8003")

# One canonical asset (P-101A) seen by both CMMS systems under different source handles.
ASSET = uuid4()
MAXIMO_LOC = "CRDU-P101A"   # P-101A's maximo_location
SAP_EQUNR = "10001234"      # P-101A's sap_equipment
SEAL_LEAK = "seal leak confirmed"   # substring of the shared seal-leak narrative


def _reachable(url: str) -> bool:
    try:
        return httpx.get(f"{url}/openapi.json", timeout=1.0).status_code < 500
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable(MAXIMO_SIM_URL) and _reachable(SAP_SIM_URL)),
    reason=f"both CMMS sims must be up ({MAXIMO_SIM_URL} + {SAP_SIM_URL}); run `task parity:cross`",
)


def _parse(result) -> "ToolResponse[list[WorkOrder]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def _maximo_workorders() -> list[WorkOrder]:
    bindings = {(ASSET, "maximo"): SourceBinding(handle=MAXIMO_LOC, raw_unit="n/a")}
    async with httpx.AsyncClient(base_url=MAXIMO_SIM_URL) as http:
        mcp = make_maximo_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            resp = _parse(await client.call_tool(
                "maximo.get_workorders", {"request": {"asset_id": str(ASSET)}}))
    assert resp.error is None, resp.error
    return resp.data


async def _sap_notifications() -> list[WorkOrder]:
    bindings = {(ASSET, "sap_pm"): SourceBinding(handle=SAP_EQUNR, raw_unit="n/a")}
    async with httpx.AsyncClient(base_url=SAP_SIM_URL) as http:
        mcp = make_sap_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            resp = _parse(await client.call_tool(
                "sap_pm.get_notifications", {"request": {"asset_id": str(ASSET)}}))
    assert resp.error is None, resp.error
    return resp.data


def _seal_leak(work_orders: list[WorkOrder]) -> WorkOrder:
    matches = [w for w in work_orders if SEAL_LEAK in w.description.lower()]
    assert matches, f"no seal-leak work order found in {[w.description for w in work_orders]}"
    return matches[0]


async def test_both_cmms_sources_unify_under_canonical_workorder():
    maximo = await _maximo_workorders()
    sap = await _sap_notifications()

    # Both sources produce canonical WorkOrders for the SAME asset, each correctly labeled.
    assert maximo and sap
    assert all(w.source_system == "maximo" and str(w.asset_id) == str(ASSET) for w in maximo)
    assert all(w.source_system == "sap_pm" and str(w.asset_id) == str(ASSET) for w in sap)
    assert all(w.opened_at.tzinfo is not None for w in maximo + sap)   # both UTC-normalized

    # The seal-leak event exists in BOTH systems and converges on the same canonical
    # failure code (Maximo failurecode + SAP FECOD 0010 -> ISO-14224 "LEK").
    maximo_leak = _seal_leak(maximo)
    sap_leak = _seal_leak(sap)
    assert maximo_leak.failure_code == "LEK"
    assert sap_leak.failure_code == "LEK"
    assert maximo_leak.source_system != sap_leak.source_system   # genuinely two sources
