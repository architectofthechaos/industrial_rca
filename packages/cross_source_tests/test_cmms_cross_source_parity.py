"""Cross-source parity: SAP PM and Maximo unify under the canonical WorkOrder.

Proves the central promise of the connector layer — that two different CMMS sources,
talking different protocols (SAP OData v2 vs Maximo OSLC) with different identifiers
(EQUNR `10001234` vs location `CRDU-P101A`) and different code schemes (SAP FECOD vs
Maximo failurecode) — both translate to the SAME canonical `WorkOrder` shape for the
SAME logical asset (P-101A), and converge on the SAME ISO-14224 failure code (`LEK`)
for the seal-leak event that appears in both systems.

The Maximo leg now drives the **entity** `work_order` MCP (`make_work_order_mcp`):
ConnectionRouter resolves the cmms connection from the canonical_id's plant, and a
StaticAssetGateway maps the canonical_id to the Maximo location. The SAP leg still uses
`make_sap_mcp` + `sap_pm.get_notifications` — sap_pm is parked (excluded from `task test`),
but this cross-source test historically exercises it and runs only under `task parity:cross`.

Requires BOTH the Maximo (:8002) and SAP (:8003) simulators; skips otherwise. Talks only
HTTP — never imports rca_simulator (ADR-0012). Run with: `task parity:cross`.
"""
import json
import os
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_sap_pm.server import make_sap_mcp
from rca_connector_sdk import (
    ConnectionInfo,
    SourceBinding,
    StaticAssetGateway,
    StaticConnectionRouter,
)
from rca_contracts import ToolResponse, WorkOrder

MAXIMO_SIM_URL = os.environ.get("MAXIMO_SIM_URL", "http://127.0.0.1:8002")
SAP_SIM_URL = os.environ.get("SAP_SIM_URL", "http://127.0.0.1:8003")

# One logical asset (P-101A) seen by both CMMS systems under different source handles.
# The two legs key the asset differently by design: the entity work_order MCP stamps a
# deterministic asset_id from the canonical_id (no MAR-bound UUID at this altitude), while
# the SAP leg is asset-scoped on an explicit AssetID. The point of the test is that BOTH
# emit canonical WorkOrders for the same logical pump and converge on the same ISO code.
CANONICAL = "asset:refinery-gc:unit-101:p-101a"
SAP_ASSET = uuid4()
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
    # Entity work_order MCP: router -> cmms connection; gateway maps canonical_id -> location.
    router = StaticConnectionRouter([ConnectionInfo(
        connection_id="refinery-gc.cmms.maximo-main", plant_id="refinery-gc", category="cmms",
        connector_type="maximo", base_url=MAXIMO_SIM_URL,
    )])
    assets = StaticAssetGateway(handles={(CANONICAL, "cmms"): MAXIMO_LOC})
    mcp = make_work_order_mcp(router=router, assets=assets)
    async with Client(mcp) as client:
        resp = _parse(await client.call_tool(
            "work_order.list_for_asset", {"request": {"canonical_id": CANONICAL}}))
    assert resp.error is None, resp.error
    return resp.data


async def _sap_notifications() -> list[WorkOrder]:
    bindings = {(SAP_ASSET, "sap_pm"): SourceBinding(handle=SAP_EQUNR, raw_unit="n/a")}
    async with httpx.AsyncClient(base_url=SAP_SIM_URL) as http:
        mcp = make_sap_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            resp = _parse(await client.call_tool(
                "sap_pm.get_notifications", {"request": {"asset_id": str(SAP_ASSET)}}))
    assert resp.error is None, resp.error
    return resp.data


def _seal_leak(work_orders: list[WorkOrder]) -> WorkOrder:
    matches = [w for w in work_orders if SEAL_LEAK in w.description.lower()]
    assert matches, f"no seal-leak work order found in {[w.description for w in work_orders]}"
    return matches[0]


async def test_both_cmms_sources_unify_under_canonical_workorder():
    maximo = await _maximo_workorders()
    sap = await _sap_notifications()

    # Both sources produce canonical WorkOrders for the SAME logical asset, each correctly
    # labeled by its source_system. Each leg is internally consistent on its own asset_id.
    assert maximo and sap
    assert all(w.source_system == "maximo" for w in maximo)
    assert all(w.source_system == "sap_pm" and str(w.asset_id) == str(SAP_ASSET) for w in sap)
    assert len({str(w.asset_id) for w in maximo}) == 1   # one logical asset on the maximo leg
    assert all(w.opened_at.tzinfo is not None for w in maximo + sap)   # both UTC-normalized

    # The seal-leak event exists in BOTH systems and converges on the same canonical
    # failure code (Maximo failurecode + SAP FECOD 0010 -> ISO-14224 "LEK").
    maximo_leak = _seal_leak(maximo)
    sap_leak = _seal_leak(sap)
    assert maximo_leak.failure_code == "LEK"
    assert sap_leak.failure_code == "LEK"
    assert maximo_leak.source_system != sap_leak.source_system   # genuinely two sources
