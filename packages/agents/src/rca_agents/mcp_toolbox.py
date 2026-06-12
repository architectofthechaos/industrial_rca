"""Live ToolBox adapter (WI2, G7/G10).

``McpToolBox`` implements the ``ToolBox`` Protocol by driving the mounted entity MCP host
through a transport-agnostic ``fastmcp.Client`` and adapting each tool's ``ToolResponse`` to
the shape the agents read (see ``FakeToolBox`` for the reference shape). This module imports
ONLY ``fastmcp`` + ``rca_contracts`` — never a connector/MAR/KG/simulator module (§8 invariant).
Source routing is endpoint/config-driven inside the host the client points at; the in-process
vs HTTP choice is purely how the ``Client`` is constructed at startup.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean as _mean
from typing import Any
from uuid import uuid4

from rca_contracts import ProvenanceEntry, ToolResponse


def severity_for(*, mean: float, mx: float) -> str:
    """Coarse stand-in severity from per-tag stats (real anomaly detection is the LLM's job
    downstream; the toolbox only supplies stats + a hint)."""
    if mean and mx >= 2.0 * mean:
        return "critical"
    if mean and mx >= 1.5 * mean:
        return "elevated"
    return "normal"


def summarize_series(series: dict, *, role: str | None, lookback_hours: int) -> dict:
    values = [float(v["value"]) for v in series.get("values", []) if v.get("value") is not None]
    tag_name = (series.get("tag") or {}).get("tag_name") or series.get("tag_name")
    if not values:
        return {"tag_name": tag_name, "role": role, "summary": "no samples in window",
                "mean": None, "max": None, "severity": "normal"}
    mn, mx, first, last = _mean(values), max(values), values[0], values[-1]
    return {
        "tag_name": tag_name, "role": role,
        "summary": f"{role or tag_name}: {first:.1f} -> {last:.1f} "
                   f"(min {min(values):.1f}, max {mx:.1f}) over {lookback_hours}h",
        "mean": round(mn, 4), "max": round(mx, 4), "severity": severity_for(mean=mn, mx=mx),
    }


def alarm_to_log(a: dict, *, index: int, canonical_id: str) -> dict:
    return {"log_id": f"log:{canonical_id}:{a.get('timestamp', index)}",
            "text": a.get("message", ""), "author": None, "at": a.get("timestamp")}


def descriptor_to_summary(d: dict, *, keywords: str) -> dict:
    cid = d["canonical_id"]
    name = d.get("tag") or cid.split(":")[-1].upper()
    kw = (keywords or "").lower()
    exact = name.lower() in kw or cid.split(":")[-1] in kw
    return {"canonical_id": cid, "name": name, "confidence": 0.95 if exact else 0.6}


__all__ = ["summarize_series", "alarm_to_log", "descriptor_to_summary", "severity_for"]
