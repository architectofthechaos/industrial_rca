"""Live ToolBox adapter (WI2, G7/G10).

``McpToolBox`` implements the ``ToolBox`` Protocol by driving the mounted entity MCP host
through a transport-agnostic ``fastmcp.Client`` and adapting each tool's ``ToolResponse`` to
the shape the agents read (see ``FakeToolBox`` for the reference shape). This module imports
ONLY ``rca_contracts`` — never a connector/MAR/KG/simulator module (§8 invariant).
Source routing is endpoint/config-driven inside the host the client points at; the in-process
vs HTTP choice is purely how the ``Client`` is constructed at startup.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import mean as _mean
from typing import Any
from uuid import uuid4

from rca_contracts import ProvenanceEntry, ToolResponse


def severity_for(*, mean: float, mx: float) -> str:
    """Coarse stand-in severity from per-tag stats (real anomaly detection is the LLM's job
    downstream; the toolbox only supplies stats + a hint). Unit-agnostic ratio rule."""
    if not mean:
        return "normal"
    ratio = mx / mean
    if ratio >= 2.0:
        return "critical"
    if ratio >= 1.5:
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
    # 0.5 = neutral middle; asset.search is a structured filter, not a fuzzy scorer
    return {"canonical_id": cid, "name": name, "confidence": 0.95 if exact else 0.5}


class McpToolBox:
    """Production ToolBox over a mounted entity MCP host (in-process or HTTP fastmcp.Client)."""

    def __init__(self, client: Any, *, plant_id: str | None = None) -> None:
        self._c = client            # an *open* fastmcp.Client
        self._plant_id = plant_id

    async def _call(self, tool: str, request: dict) -> ToolResponse[Any]:
        res = await self._c.call_tool(tool, {"request": request})
        payload = res.structured_content
        if payload is None:
            raise RuntimeError(f"{tool} returned no structured content: {res.data!r}")
        # Tools serialize their ToolResponse to a JSON-mode dict over the wire (ISO datetimes,
        # string UUIDs), so validate non-strictly to coerce those back; the envelope's
        # exactly-one-of invariant still runs.
        return ToolResponse[Any].model_validate(payload, strict=False)

    @staticmethod
    def _require_ok(resp: ToolResponse[Any], tool: str) -> ToolResponse[Any]:
        if resp.error is not None:
            raise RuntimeError(f"{tool} failed: {resp.error}")
        return resp

    @staticmethod
    def _conn_id(resp: ToolResponse[Any]) -> str | None:
        return resp.provenance.connection_id if resp.provenance else None

    async def search_assets(self, keywords: str, plant_id: str | None) -> list[dict]:
        # Planning passes the full prompt as `keywords`. Search by each equipment-tag-like token
        # (e.g. "P-101A"); MAR's asset.search ANDs its filters and is case-sensitive, so use
        # tag_pattern ONLY. If no token matches, fall back to the plant's asset list so the LLM
        # always has a shortlist to resolve from (G21).
        rows: list[dict] = []
        for tok in _tag_tokens(keywords):
            resp = await self._call("asset.search", {"tag_pattern": f"%{tok}%"})
            rows = resp.data or []
            if rows:
                break
        if not rows:
            resp = await self._call("asset.search", {})
            rows = resp.data or []
        return [descriptor_to_summary(d, keywords=keywords) for d in rows]

    async def asset_summary(self, canonical_id: str) -> dict | None:
        resp = await self._call("asset.get", {"canonical_id": canonical_id})
        if resp.error is not None:
            return None
        return dict(resp.data) if resp.data else None

    async def get_asset_context(self, canonical_id: str,
                                iso14224_class: str | None = None) -> dict:
        if iso14224_class is None:
            a = await self.asset_summary(canonical_id) or {}
            iso14224_class = a.get("iso14224_class_kg") or a.get("iso14224_class")
        req = {"canonical_id": canonical_id}
        if iso14224_class is not None:
            req["iso14224_class"] = iso14224_class
        resp = await self._call("kg.get_asset_context", req)
        self._require_ok(resp, "kg.get_asset_context")
        ctx = dict(resp.data or {})
        if iso14224_class is not None and not ctx.get("iso14224_class"):
            ctx["iso14224_class"] = iso14224_class
        return ctx

    async def tag_history(self, canonical_id: str, *, reference_time: datetime,
                          lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        listed = await self._call("tag.list_for_asset", {"canonical_id": canonical_id})
        self._require_ok(listed, "tag.list_for_asset")
        start = reference_time - timedelta(hours=lookback_hours)
        out: list[dict] = []
        conn = self._conn_id(listed)
        for t in (listed.data or []):
            # interpolated (evenly-spaced, downsampled) — not raw "stored" points: the toolbox
            # only needs summary stats, and a multi-day "stored" window returns ~550k points/tag
            # (~25s), blowing the gather-leg timeout. Interpolated is ~10k points/tag (~0.6s) (G24).
            hist = await self._call("tag.get_history", {
                "canonical_id": canonical_id, "tag_name": t["tag_name"],
                "start": start.isoformat(), "end": reference_time.isoformat(),
                "mode": "interpolated"})
            self._require_ok(hist, "tag.get_history")
            # last-response connection_id used (single historian per asset assumption)
            conn = self._conn_id(hist) or conn
            out.append(summarize_series(hist.data or {}, role=t.get("role"),
                                        lookback_hours=lookback_hours))
        prov = ProvenanceEntry(section="tag", item_id=canonical_id, tool_name="tag.get_history",
                               connection_id=conn, queried_at=reference_time,
                               response_id=uuid4(), record_count=len(out))
        return out, prov

    async def work_orders_for_asset(self, canonical_id: str
                                    ) -> tuple[list[dict], ProvenanceEntry]:
        resp = await self._call("work_order.list_for_asset", {"canonical_id": canonical_id})
        self._require_ok(resp, "work_order.list_for_asset")
        rows = [dict(w) for w in (resp.data or [])]
        prov = ProvenanceEntry(section="work_order", item_id=canonical_id,
                               tool_name="work_order.list_for_asset",
                               connection_id=self._conn_id(resp), queried_at=_qa(resp, canonical_id),
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    async def documents_for_asset(self, canonical_id: str, query: str
                                  ) -> tuple[list[dict], ProvenanceEntry]:
        resp = await self._call("document.search_for_asset",
                                {"canonical_id": canonical_id, "query": query})
        self._require_ok(resp, "document.search_for_asset")
        rows = [dict(d) for d in (resp.data or [])]
        prov = ProvenanceEntry(section="document", item_id=canonical_id,
                               tool_name="document.search_for_asset",
                               connection_id=self._conn_id(resp), queried_at=_qa(resp, canonical_id),
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    async def operator_logs_for_asset(self, canonical_id: str, *, reference_time: datetime,
                                      lookback_hours: int) -> tuple[list[dict], ProvenanceEntry]:
        start = reference_time - timedelta(hours=lookback_hours)
        resp = await self._call("operator_log.list_for_asset", {
            "canonical_id": canonical_id, "start": start.isoformat(),
            "end": reference_time.isoformat()})
        self._require_ok(resp, "operator_log.list_for_asset")
        rows = [alarm_to_log(a, index=i, canonical_id=canonical_id)
                for i, a in enumerate(resp.data or [])]
        prov = ProvenanceEntry(section="operator_log", item_id=canonical_id,
                               tool_name="operator_log.list_for_asset",
                               connection_id=self._conn_id(resp), queried_at=reference_time,
                               response_id=uuid4(), record_count=len(rows))
        return rows, prov

    async def upsert_asset(self, *, canonical_id: str, name: str, iso14224_class: str,
                           confidence: float, method: str, reference_time: datetime) -> bool:
        resp = await self._call("kg.upsert_asset", {
            "canonical_id": canonical_id, "name": name, "iso14224_class": iso14224_class,
            "iso14224_class_confidence": confidence, "iso14224_class_method": method,
            "reference_time": reference_time.isoformat()})
        if resp.error is not None:
            raise RuntimeError(f"kg.upsert_asset failed: {resp.error}")
        return bool((resp.data or {}).get("created", False))

    async def link_failure_mode(self, *, canonical_id: str, failure_mode_code: str) -> bool:
        resp = await self._call("kg.link_failure_mode", {
            "canonical_id": canonical_id, "failure_mode_code": failure_mode_code})
        return resp.error is None

    async def failure_modes_for_class(self, equipment_class_id: str) -> list[dict]:
        resp = await self._call("kg.list_failure_modes_for_class",
                                {"equipment_class_id": equipment_class_id})
        self._require_ok(resp, "kg.list_failure_modes_for_class")
        return [dict(e) for e in (resp.data or [])]


_TAG_RE = re.compile(r"[A-Za-z]{1,5}-?\d{2,}[A-Za-z]?")


def _tag_tokens(keywords: str) -> list[str]:
    """Equipment-tag-like tokens from free text (e.g. "P-101A"), uppercased to match MAR tags.

    Requires digits, so plain uppercase words ("RCA") are not mistaken for asset tags.
    """
    return [m.group(0).upper() for m in _TAG_RE.finditer(keywords or "")]


def _qa(resp: ToolResponse[Any], canonical_id: str) -> datetime:
    if resp.provenance and resp.provenance.queried_at:
        return resp.provenance.queried_at
    raise RuntimeError("connector response missing provenance.queried_at")


__all__ = ["McpToolBox", "summarize_series", "alarm_to_log", "descriptor_to_summary",
           "severity_for"]
