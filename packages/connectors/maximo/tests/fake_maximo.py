"""A small FastAPI fake of the Maximo OSLC mxwo surface for the work_order MCP tests.

Serves the routes the work_order tools call (GET /maxrest/oslc/os/mxwo with an oslc.where
filter, plus /openapi.json via FastAPI) with three seeded work orders at location
CRDU-P101A. Hermetic: the product test venv never imports rca_simulator — the connector
talks REST exactly as it would to a real Maximo server.
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query

# Three WOs at the same location, with distinct reportdates so list_recent ordering is testable.
_WORK_ORDERS: list[dict[str, Any]] = [
    {"wonum": "WO-50012345", "location": "CRDU-P101A", "description": "seal leak confirmed",
     "status": "COMP", "reportdate": "2026-03-28T19:00:00", "worktype": "CM",
     "wopriority": 1, "problemcode": "LEAK", "failurecode": "LEK"},
    {"wonum": "WO-50012402", "location": "CRDU-P101A", "description": "vibration trend high",
     "status": "WAPPR", "reportdate": "2026-03-30T08:30:00", "worktype": "PdM",
     "wopriority": 2, "problemcode": "VIB", "failurecode": None},
    {"wonum": "WO-49900001", "location": "CRDU-P101A", "description": "routine inspection",
     "status": "COMP", "reportdate": "2025-10-02T08:00:00", "worktype": "PM",
     "wopriority": 3, "problemcode": None, "failurecode": None},
]


def _parse_where(where: str | None) -> dict[str, str]:
    """Parse the subset of oslc.where the connector sends: field="value" [and ...]."""
    out: dict[str, str] = {}
    if not where:
        return out
    import re
    for field, value in re.findall(r'(\w+)\s*=\s*"([^"]*)"', where):
        out[field] = value
    return out


def build_fake_maximo() -> FastAPI:
    app = FastAPI(title="Maximo OSLC Simulator", version="7.6.1")
    # Per-app mutable store seeded from the baseline (mirrors the real sim's in-memory upsert).
    work_orders: dict[str, dict[str, Any]] = {w["wonum"]: dict(w) for w in _WORK_ORDERS}

    @app.get("/maxrest/oslc/os/mxwo")
    def mxwo(where: str | None = Query(None, alias="oslc.where")) -> dict[str, Any]:
        conds = _parse_where(where)
        records = [
            w for w in work_orders.values()
            if all(str(w.get(f)) == v for f, v in conds.items())
        ]
        return {"member": records, "responseInfo": {"totalCount": len(records)}}

    @app.post("/maxrest/oslc/os/mxwo")
    def mxwo_create(record: dict = Body(...)) -> dict[str, Any]:
        wonum = record.get("wonum")
        if not wonum:
            raise HTTPException(status_code=400, detail="wonum required")
        # idempotent upsert by wonum, exactly like the real sim
        work_orders[wonum] = {**work_orders.get(wonum, {}), **record}
        return work_orders[wonum]

    return app


__all__ = ["build_fake_maximo"]
