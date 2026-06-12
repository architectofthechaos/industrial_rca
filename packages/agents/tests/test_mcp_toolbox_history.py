"""tag_history uses interpolated (downsampled) history, not raw stored points (Sprint 5 G24).

The live run surfaced that `mode="stored"` returns ~550k recorded points per tag over a 7-day
window (~25s/tag) — 6 tags blew the 5-minute gather-leg timeout (CancelledError). The toolbox
only needs summary stats (mean/max/trend), so it must request interpolated/evenly-spaced data
(~10k points, ~0.6s/tag). This pins the request mode against a recording stub host.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastmcp import Client, FastMCP

from rca_agents.mcp_toolbox import McpToolBox

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
CID = "asset:refinery-gc:unit-101:p-101a"


def _ok(data, connection_id=None):
    return {"data": data,
            "provenance": {"tool_name": "x", "tool_version": "v1", "source": "pi",
                           "connection_id": connection_id, "source_query": "q",
                           "queried_at": REF.isoformat(),
                           "response_id": "0190d3c9-0000-7000-8000-000000000abc",
                           "record_count": 1, "truncated": False, "raw_tags": [], "notes": None},
            "error": None}


@pytest.mark.asyncio
async def test_tag_history_requests_interpolated_not_stored():
    seen_modes: list[str] = []
    h = FastMCP("hist-stub")

    @h.tool(name="tag.list_for_asset")
    async def lst(request: dict):
        return _ok([{"tag_name": "P-101A.vibration_radial", "role": "vibration_radial"}],
                   connection_id="refinery-gc.historian.pi-main")

    @h.tool(name="tag.get_history")
    async def hist(request: dict):
        seen_modes.append(request.get("mode"))
        return _ok({"tag": {"tag_name": request["tag_name"]}, "values": [{"value": 2.1}]},
                   connection_id="refinery-gc.historian.pi-main")

    async with Client(h) as client:
        tags, _ = await McpToolBox(client).tag_history(CID, reference_time=REF, lookback_hours=168)
    assert seen_modes == ["interpolated"], (
        f"tag_history must request interpolated (downsampled) history; sent {seen_modes}")
    assert tags and tags[0]["tag_name"] == "P-101A.vibration_radial"
