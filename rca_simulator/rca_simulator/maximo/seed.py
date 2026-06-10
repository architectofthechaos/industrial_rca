"""S2.3 — seed Maximo work orders / service requests / failure reports.

Combines the scenario timelines (events with ``sink: maximo``) with the baseline
historical work-order seeds, shaped into Maximo attribute names (``wonum``,
``location``, ``reportdate`` …). Timestamps are emitted as local-time-without-TZ
to exercise the connector's normalization path; some failure records carry legacy
plant-specific (non-ISO-14224) codes.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import events_by_sink

_WORKTYPE = {"corrective": "CM", "preventive": "PM", "predictive": "PdM"}


def to_local_naive(dt: datetime, tz_name: str) -> str:
    """UTC -> site-local wall-clock string with no tz suffix (Maximo style)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _location(rp: RefPlant, asset_tag: str) -> str:
    asset = rp.assets.get(asset_tag)
    if asset is None:
        return asset_tag
    return str(asset.external_ids.get("maximo_location", asset_tag))


def seed_work_orders(rp: RefPlant) -> list[dict]:
    tz = rp.plant.site.timezone
    site = rp.plant.site.site_id
    out: list[dict] = []

    # scenario-driven work orders
    for sid, sc in rp.scenarios.items():
        for ts, ev in events_by_sink(rp, sid).get("maximo", []):
            p = ev.payload
            out.append({
                "wonum": p["wo_number"],
                "location": _location(rp, sc.affected_asset),
                "description": p.get("narrative", ""),
                "status": "COMP",
                "reportdate": to_local_naive(ts, tz),
                "worktype": _WORKTYPE.get(p.get("type", ""), "CM"),
                "wopriority": p.get("priority"),
                "problemcode": p.get("problem_code"),
                "failurecode": p.get("failure_code"),
                "siteid": site,
            })

    # baseline historical seeds
    for seed in rp.work_orders:
        for wo in seed.work_orders:
            out.append({
                "wonum": wo["wo_number"],
                "location": _location(rp, wo.get("asset", "")),
                "description": wo.get("narrative", ""),
                "status": wo.get("status", "COMP").upper(),
                "reportdate": _naive_or_passthrough(wo.get("opened", ""), tz),
                "worktype": _WORKTYPE.get(wo.get("type", ""), "CM"),
                "wopriority": wo.get("priority"),
                "problemcode": wo.get("problem_code"),
                "failurecode": wo.get("failure_code"),
                "siteid": site,
            })
    return out


def _naive_or_passthrough(value: str, tz: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return to_local_naive(dt, tz)


def seed_failure_reports(rp: RefPlant) -> list[dict]:
    """Failure reports for WOs carrying a failure code, plus one legacy-coded record."""
    out: list[dict] = []
    for wo in seed_work_orders(rp):
        if wo.get("failurecode"):
            out.append({
                "failurenum": f"FR-{wo['wonum']}",
                "wonum": wo["wonum"],
                "location": wo["location"],
                "failurecode": wo["failurecode"],   # ISO-14224 where present
                "reportdate": wo["reportdate"],
            })
    # one legacy plant-specific code (real-world messiness)
    out.append({
        "failurenum": "FR-LEGACY-0001",
        "wonum": "WO-49900001",
        "location": _location(rp, "P-101A"),
        "failurecode": "SEAL-LEG-07",              # non-ISO-14224 legacy code
        "reportdate": to_local_naive(datetime(2025, 10, 2, 8, 0), rp.plant.site.timezone),
    })
    return out


def seed_service_requests(rp: RefPlant) -> list[dict]:
    """Service requests derived from scenario alarm/operator events."""
    tz = rp.plant.site.timezone
    out: list[dict] = []
    n = 1
    for sid, sc in rp.scenarios.items():
        sinks = events_by_sink(rp, sid)
        for ts, ev in sinks.get("alarms", []) + sinks.get("documents", []):
            out.append({
                "ticketid": f"SR-{sid[:4].upper()}-{n:03d}",
                "location": _location(rp, sc.affected_asset),
                "description": ev.payload.get("text") or ev.payload.get("alarm_id", ""),
                "reportdate": to_local_naive(ts, tz),
                "status": "QUEUED",
            })
            n += 1
    return out


__all__ = [
    "to_local_naive", "seed_work_orders", "seed_failure_reports", "seed_service_requests",
]
