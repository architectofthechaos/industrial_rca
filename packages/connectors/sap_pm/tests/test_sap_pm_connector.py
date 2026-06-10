"""S13.4 SAP PM connector test: sap_pm.get_notifications end-to-end through MCP.

Hermetic in-test SAP OData v2 fake. Verifies asset-scoped resolution, the OData
envelope, and FECOD->ISO code normalization into the canonical WorkOrder.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastmcp import Client
from rca_connector_sdk import SourceBinding
from rca_contracts import ToolResponse, WorkOrder

from rca_connector_sap_pm.server import make_sap_mcp

ASSET = uuid4()
EQUNR = "10001234"
SRV = "/sap/opu/odata/sap/PM_NOTIFICATION_SRV"


def _build_sap_fake() -> FastAPI:
    app = FastAPI(title="SAP fake")

    @app.get(f"{SRV}/NotificationSet")
    def notifications(filter: str | None = None):   # noqa: A002 — OData uses $filter
        return {"d": {"results": [
            {"QMNUM": "10000123", "EQUNR": EQUNR, "QMTXT": "seal leak confirmed",
             "QMART": "M2", "PRIOK": "1", "FECOD": "0010", "AUSVN": "20260318"},
        ]}}

    return app


def _parse(result) -> "ToolResponse[list[WorkOrder]]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[list[WorkOrder]].model_validate_json(json.dumps(payload))


async def test_get_notifications_normalizes_to_workorder():
    transport = httpx.ASGITransport(app=_build_sap_fake())
    bindings = {(ASSET, "sap_pm"): SourceBinding(handle=EQUNR, raw_unit="n/a")}
    async with httpx.AsyncClient(transport=transport, base_url="http://sap") as http:
        mcp = make_sap_mcp(http_client=http, bindings=bindings)
        async with Client(mcp) as client:
            assert "sap_pm.get_notifications" in {t.name for t in await client.list_tools()}

            res = await client.call_tool(
                "sap_pm.get_notifications", {"request": {"asset_id": str(ASSET)}}
            )
            resp = _parse(res)
            assert resp.error is None and resp.data is not None
            wo = resp.data[0]
            assert wo.work_order_id == "10000123"
            assert str(wo.asset_id) == str(ASSET)            # canonical asset from the request
            assert wo.failure_code == "LEK"                  # FECOD 0010 -> ISO LEK
            assert wo.source_system == "sap_pm"
            assert wo.opened_at.tzinfo is not None
            assert resp.provenance.record_count == 1
            assert EQUNR in resp.provenance.raw_tags         # forensic source id


async def test_opened_at_honors_configured_source_timezone():
    # SAP's AUSVN ("20260318") is tz-less; it must be interpreted in the configured
    # source_timezone and converted to UTC (not silently stamped as UTC).
    transport = httpx.ASGITransport(app=_build_sap_fake())
    bindings = {(ASSET, "sap_pm"): SourceBinding(handle=EQUNR, raw_unit="n/a")}
    async with httpx.AsyncClient(transport=transport, base_url="http://sap") as http:
        mcp = make_sap_mcp(http_client=http, bindings=bindings, source_timezone="America/Chicago")
        async with Client(mcp) as client:
            res = await client.call_tool(
                "sap_pm.get_notifications", {"request": {"asset_id": str(ASSET)}}
            )
            wo = _parse(res).data[0]
            expected = datetime(2026, 3, 18, tzinfo=ZoneInfo("America/Chicago")).astimezone(timezone.utc)
            assert wo.opened_at == expected                          # local midnight -> UTC (05:00)
            assert wo.opened_at != datetime(2026, 3, 18, tzinfo=timezone.utc)  # not the old UTC-stamp bug
