"""The SAP PM connector's tools. S13.4 slice: sap_pm.get_notifications (read-only)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from rca_connector_sdk import evidence_tool, to_utc
from rca_contracts import AssetID, WorkOrder

_SRV = "/sap/opu/odata/sap/PM_NOTIFICATION_SRV"

# SAP FECOD code scheme -> canonical ISO 14224 code (normalization; matches Maximo's codes)
_FECOD_TO_ISO = {"0010": "LEK", "0020": "VIB", "0030": "ELE", "0040": "VIB"}


class GetNotificationsRequest(BaseModel):
    asset_id: AssetID


@evidence_tool(
    name="sap_pm.get_notifications", version="0.1.0", source="sap_pm",
    request=GetNotificationsRequest, response=list[WorkOrder],
)
class SapNotifications:
    async def fetch(self, ctx, req: GetNotificationsRequest):
        equnr = ctx.source.handle                          # EQUNR from the resolver binding
        resp = await ctx.http.get(
            f"{_SRV}/NotificationSet", params={"$filter": f"EQUNR eq '{equnr}'"}
        )
        resp.raise_for_status()                            # reads need no CSRF
        results = resp.json()["d"]["results"]
        ctx.prov.record(source_query=str(resp.request.url),
                        raw_tags=[equnr], record_count=len(results))
        return results

    def translate(self, ctx, raw) -> list[WorkOrder]:
        asset_id = ctx.request.asset_id
        tz = ctx.config.source_timezone        # interpret SAP's tz-less AUSVN in the source tz (like Maximo)
        orders: list[WorkOrder] = []
        for n in raw:
            fecod = n.get("FECOD") or None
            orders.append(WorkOrder(
                work_order_id=n["QMNUM"],
                asset_id=asset_id,
                opened_at=to_utc(datetime.strptime(n["AUSVN"], "%Y%m%d"), tz),
                closed_at=None,
                priority=str(n.get("PRIOK", "")),
                status=str(n.get("QMART", "")),
                failure_code=_FECOD_TO_ISO.get(fecod, fecod) if fecod else None,
                description=n.get("QMTXT", ""),
                source_system="sap_pm",
            ))
        return orders


__all__ = ["GetNotificationsRequest", "SapNotifications"]
