"""S2.2 — PI Web API REST simulator (FastAPI).

Implements the subset the PI connector calls: ``/streams/{webId}/recorded``,
``/interpolated``, ``/summary`` and ``/eventframes``, plus (Sprint 1 WI3) the
PI AF asset-hierarchy surface: ``/assetdatabases`` and ``/elements`` routes
backed by the element index in :mod:`.af_hierarchy`.

Time params are absolute ISO 8601 (``startTime``/``endTime``). Relative PI time
syntax ("*-1d") is out of scope for MVP.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import events_by_sink
from ..realism.config import RealismConfig
from ..realism.inject import RealismInjector
from . import synthesize
from .af_hierarchy import DEFAULT_AF_DATABASE, DEFAULT_MAX_COUNT, AfIndex, select
from .webid import decode_webid, encode_webid

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_interval(value: str, default: int) -> int:
    if not value:
        return default
    value = value.strip()
    if value[-1] in _UNITS:
        return int(float(value[:-1]) * _UNITS[value[-1]])
    return int(value)


def _pt(p: synthesize.PiPoint) -> dict:
    item = {"Timestamp": _iso(p.timestamp), "Value": p.value, "Good": p.good,
            "Questionable": not p.good, "Substituted": False}
    if p.is_interpolated:
        item["IsInterpolated"] = True
    return item


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(
    rp: RefPlant,
    *,
    scenario_id: str,
    seed: int = 0,
    realism: RealismInjector | None = None,
    af_database: str = DEFAULT_AF_DATABASE,
) -> FastAPI:
    app = FastAPI(title="PI Web API Simulator")
    af = AfIndex(rp, database=af_database)

    def resolve(web_id: str) -> str:
        try:
            key = decode_webid(web_id)
        except Exception:
            raise HTTPException(status_code=404, detail="WebID not found")
        if key not in rp.signals:
            raise HTTPException(status_code=404, detail="WebID not found")
        return key

    @app.get("/streams/{web_id}/recorded")
    def recorded(web_id: str, startTime: str, endTime: str):
        key = resolve(web_id)
        pts = synthesize.recorded(rp, scenario_id, key,
                                  _parse_time(startTime), _parse_time(endTime),
                                  seed=seed, realism=realism)
        return {"Items": [_pt(p) for p in pts]}

    @app.get("/streams/{web_id}/interpolated")
    def interpolated(web_id: str, startTime: str, endTime: str, interval: str = "60s"):
        key = resolve(web_id)
        pts = synthesize.interpolated(rp, scenario_id, key,
                                      _parse_time(startTime), _parse_time(endTime),
                                      _parse_interval(interval, 60),
                                      seed=seed, realism=realism)
        return {"Items": [_pt(p) for p in pts]}

    @app.get("/streams/{web_id}/summary")
    def summary(web_id: str, startTime: str, endTime: str,
                summaryType: str = "Average", summaryDuration: str = "1h"):
        key = resolve(web_id)
        agg = synthesize.aggregated(rp, scenario_id, key,
                                    _parse_time(startTime), _parse_time(endTime),
                                    _parse_interval(summaryDuration, 3600),
                                    summaryType, seed=seed)
        return {"Items": [
            {"Type": summaryType,
             "Value": {"Timestamp": _iso(ts), "Value": value, "Good": True}}
            for ts, value in agg
        ]}

    @app.get("/eventframes")
    def eventframes(startTime: str, endTime: str):
        start, end = _parse_time(startTime), _parse_time(endTime)
        items = []
        for sc_id in rp.scenarios:
            for ts, ev in events_by_sink(rp, sc_id).get("alarms", []):
                if start <= ts <= end:
                    duration_min = ev.payload.get("duration_min", 0)
                    items.append({
                        "Name": ev.payload.get("alarm_id", "ALARM"),
                        "StartTime": _iso(ts),
                        "EndTime": _iso(ts + timedelta(minutes=duration_min)),
                        "Template": ev.payload.get("level", "alarm"),
                        "Signal": ev.payload.get("signal"),
                    })
        return {"Items": items}

    # ---- PI AF asset hierarchy (Sprint 1 WI3) -------------------------------
    # NOTE: 404 bodies use FastAPI's {"detail": "..."} shape, not PI's
    # {"Errors": [...]} envelope — accepted Sprint-1 deviation.

    def resolve_element(web_id: str):
        el = af.element(web_id)
        if el is None:
            raise HTTPException(status_code=404, detail="Element not found")
        return el

    def resolve_database(web_id: str):
        if web_id != af.database.web_id:
            raise HTTPException(status_code=404, detail="Asset database not found")
        return af.database

    @app.get("/assetdatabases")
    def assetdatabases():
        return {"Items": [af.database.as_item()]}

    @app.get("/assetdatabases/{web_id}")
    def assetdatabase(web_id: str):
        return resolve_database(web_id).as_item()

    @app.get("/assetdatabases/{web_id}/elements")
    def database_elements(web_id: str, nameFilter: str | None = None,
                          searchFullHierarchy: bool = False,
                          maxCount: int = DEFAULT_MAX_COUNT):
        db = resolve_database(web_id)
        els = select(db.roots, name_filter=nameFilter,
                     search_full_hierarchy=searchFullHierarchy, max_count=maxCount)
        return {"Items": [el.as_item() for el in els]}

    @app.get("/elements/{web_id}")
    def element(web_id: str):
        return resolve_element(web_id).as_item()

    @app.get("/elements/{web_id}/elements")
    def element_children(web_id: str, nameFilter: str | None = None,
                         searchFullHierarchy: bool = False,
                         maxCount: int = DEFAULT_MAX_COUNT):
        el = resolve_element(web_id)
        els = select(el.children, name_filter=nameFilter,
                     search_full_hierarchy=searchFullHierarchy, max_count=maxCount)
        return {"Items": [el.as_item() for el in els]}

    @app.get("/elements/{web_id}/attributes")
    def element_attributes(web_id: str):
        # Flat {WebId, Name, Value} list — the agreed Sprint 1 shape (real PI
        # has a richer attribute model with separate value endpoints).
        el = resolve_element(web_id)
        return {"Items": [
            {"WebId": encode_webid(f"{el.path}|{name}"), "Name": name, "Value": value}
            for name, value in el.attributes
        ]}

    return app


def build_default_app() -> FastAPI:
    """Entrypoint used by uvicorn / the Docker image (env-configured)."""
    import os

    from ..fixtures.loader import load

    rp = load(os.environ.get("FIXTURE_PATH", "fixtures/refplant"))
    scenario = os.environ.get("SCENARIO", "seal_leak_progression")
    return create_app(rp, scenario_id=scenario,
                      realism=RealismInjector(RealismConfig.from_env()),
                      af_database=os.environ.get("PI_AF_DATABASE", DEFAULT_AF_DATABASE))


__all__ = ["create_app", "build_default_app"]
