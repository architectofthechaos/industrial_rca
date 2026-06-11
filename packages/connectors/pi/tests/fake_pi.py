"""A small FastAPI fake of the PI Web API historian + event-frame surface.

Serves the routes the tag / operator_log connectors call, with one asset (P-101A) and two
signals (discharge_pressure in psig, motor_amps in A) plus one event frame. Hermetic: the
product test venv never imports rca_simulator — the connector talks REST exactly as it
would to a real PI server.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

# WebId is opaque to the connector; just keep it stable per signal.
_POINTS: dict[str, dict[str, Any]] = {
    "WEBID-P101A-DISCH": {
        "WebId": "WEBID-P101A-DISCH",
        "Name": "P-101A.discharge_pressure",
        "Path": "\\\\PI-FAKE\\P-101A.discharge_pressure",
        "Descriptor": "P-101A Discharge Pressure",
        "EngineeringUnits": "psig",
    },
    "WEBID-P101A-AMPS": {
        "WebId": "WEBID-P101A-AMPS",
        "Name": "P-101A.motor_amps",
        "Path": "\\\\PI-FAKE\\P-101A.motor_amps",
        "Descriptor": "P-101A Motor Amps",
        "EngineeringUnits": "A",
    },
}
_BY_NAME = {p["Name"]: p for p in _POINTS.values()}

_EVENT_FRAMES: dict[str, dict[str, Any]] = {
    "ALM-2026-03-13-9912": {
        "Name": "ALM-2026-03-13-9912",
        "StartTime": "2026-03-13T00:00:00Z",
        "EndTime": "2026-03-13T00:35:00Z",
        "Template": "warning",
        "Signal": "P-101A.vibration_radial",
    },
    "ALM-2026-03-15-7700": {
        "Name": "ALM-2026-03-15-7700",
        "StartTime": "2026-03-15T23:31:12Z",
        "EndTime": "2026-03-15T23:31:12Z",
        "Template": "trip",
        "Signal": "P-103A.motor_amps",
    },
}


def build_fake_pi() -> FastAPI:
    app = FastAPI(title="Fake PI", version="2.99.0")

    @app.get("/points")
    def points(nameFilter: str = "*", maxCount: int = 1000) -> dict[str, Any]:  # noqa: N803
        # nameFilter is a glob; support the two shapes the connector uses:
        #   "<TAG>.*"  -> all points whose Name starts with "<TAG>."
        #   "<exact>"  -> the exact-named point
        if nameFilter.endswith(".*"):
            prefix = nameFilter[:-1]  # keep the trailing "."
            items = [p for n, p in _BY_NAME.items() if n.startswith(prefix)]
        elif nameFilter == "*":
            items = list(_POINTS.values())
        else:
            items = [p for n, p in _BY_NAME.items() if n == nameFilter]
        items = sorted(items, key=lambda p: p["Name"])
        return {"Items": items[:maxCount]}

    @app.get("/points/{web_id}")
    def point_detail(web_id: str) -> dict[str, Any]:
        if web_id not in _POINTS:
            raise HTTPException(status_code=404, detail="point not found")
        return _POINTS[web_id]

    @app.get("/streams/{web_id}/recorded")
    def recorded(web_id: str, startTime: str, endTime: str) -> dict[str, Any]:  # noqa: N803
        if web_id not in _POINTS:
            raise HTTPException(status_code=404, detail="point not found")
        return {"Items": [
            {"Timestamp": "2026-03-06T00:00:00Z", "Value": 14.5, "Good": True},
            {"Timestamp": "2026-03-06T00:01:00Z", "Value": 14.7, "Good": True},
        ]}

    @app.get("/streams/{web_id}/interpolated")
    def interpolated(web_id: str, startTime: str, endTime: str,  # noqa: N803
                     interval: str = "60s") -> dict[str, Any]:
        return {"Items": [
            {"Timestamp": "2026-03-06T00:00:00Z", "Value": 14.5,
             "Good": True, "IsInterpolated": True},
            {"Timestamp": "2026-03-06T00:01:00Z", "Value": 14.6,
             "Good": True, "IsInterpolated": True},
            {"Timestamp": "2026-03-06T00:02:00Z", "Value": 14.7,
             "Good": True, "IsInterpolated": True},
        ]}

    @app.get("/streams/{web_id}/value")
    def value(web_id: str) -> dict[str, Any]:
        if web_id not in _POINTS:
            raise HTTPException(status_code=404, detail="point not found")
        return {"Timestamp": "2026-03-06T00:02:00Z", "Value": 14.9, "Good": True}

    @app.get("/eventframes")
    def eventframes(startTime: str, endTime: str) -> dict[str, Any]:  # noqa: N803
        items = [
            f for f in _EVENT_FRAMES.values()
            if not (f["EndTime"] < startTime or f["StartTime"] > endTime)
        ]
        return {"Items": items}

    @app.get("/eventframes/{frame_id}")
    def eventframe_detail(frame_id: str) -> dict[str, Any]:
        if frame_id not in _EVENT_FRAMES:
            raise HTTPException(status_code=404, detail="event frame not found")
        return _EVENT_FRAMES[frame_id]

    return app


__all__ = ["build_fake_pi"]
