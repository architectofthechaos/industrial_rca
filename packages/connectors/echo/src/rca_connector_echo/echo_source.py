"""A toy 'source' the echo connector talks to over HTTP (stands in for a real source).

Returns a canned series in a raw unit (bar). A designated 'down' signal returns 503
so the connector's error path can be exercised. In tests it's driven in-process via
httpx.ASGITransport (no network).
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException


def build_echo_source(down_signal: str | None = None) -> FastAPI:
    app = FastAPI(title="Echo Source")

    @app.get("/series/{signal_id}")
    def series(signal_id: str) -> dict:
        if down_signal is not None and signal_id == down_signal:
            raise HTTPException(status_code=503, detail="echo source down")
        # raw values in 'bar'; naive local timestamps (normalized by the connector)
        return {
            "unit": "bar",
            "points": [
                {"t": "2026-03-01T00:00:00", "v": 1.0},
                {"t": "2026-03-01T00:00:01", "v": 2.0},
                {"t": "2026-03-01T00:00:02", "v": 1.5},
            ],
        }

    return app


__all__ = ["build_echo_source"]
