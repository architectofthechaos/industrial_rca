"""S2.4 — SAP PM OData v2 simulator (FastAPI).

Serves ``/sap/opu/odata/sap/PM_NOTIFICATION_SRV`` with ``$metadata``, the
``NotificationSet`` entity set ($filter/$select), and the SAP CSRF token dance:
a GET with ``X-CSRF-Token: Fetch`` returns a token header; writes must echo it
back or are rejected with 403. Write-back is idempotent by ``QMNUM``.
"""
from __future__ import annotations

import secrets

from fastapi import Body, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import Response as RawResponse

from ..fixtures.schema import RefPlant
from .odata import apply_filter, apply_select, metadata_xml, odata_collection, parse_filter
from .seed import seed_notifications

_BASE = "/sap/opu/odata/sap/PM_NOTIFICATION_SRV"


def create_app(rp: RefPlant) -> FastAPI:
    app = FastAPI(title="SAP PM OData v2 Simulator")
    token = secrets.token_urlsafe(16)
    notifications: dict[str, dict] = {n["QMNUM"]: n for n in seed_notifications(rp)}

    def _maybe_issue_token(csrf: str | None, response: Response) -> None:
        if csrf == "Fetch":
            response.headers["X-CSRF-Token"] = token

    @app.get(f"{_BASE}/$metadata")
    def metadata():
        return RawResponse(content=metadata_xml(), media_type="application/xml")

    @app.get(f"{_BASE}/NotificationSet")
    def notification_set(
        response: Response,
        filter_: str | None = Query(None, alias="$filter"),
        select: str | None = Query(None, alias="$select"),
        csrf: str | None = Header(None, alias="X-CSRF-Token"),
    ):
        _maybe_issue_token(csrf, response)
        records = apply_filter(list(notifications.values()), parse_filter(filter_))
        records = apply_select(records, select)
        return odata_collection(records)

    @app.post(f"{_BASE}/NotificationSet", status_code=201)
    def create_notification(
        record: dict = Body(...),
        csrf: str | None = Header(None, alias="X-CSRF-Token"),
    ):
        if csrf != token:
            raise HTTPException(status_code=403, detail="CSRF token validation failed")
        qmnum = record.get("QMNUM")
        if not qmnum:
            raise HTTPException(status_code=400, detail="QMNUM required")
        notifications[qmnum] = {**notifications.get(qmnum, {}), **record}  # idempotent
        return {"d": notifications[qmnum]}

    return app


def build_default_app() -> FastAPI:
    import os

    from ..fixtures.loader import load

    rp = load(os.environ.get("FIXTURE_PATH", "fixtures/refplant"))
    return create_app(rp)


__all__ = ["create_app", "build_default_app"]
