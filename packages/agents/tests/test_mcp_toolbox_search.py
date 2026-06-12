"""search_assets adaptation tests (Sprint 5 G21).

The live run surfaced that the planning agent passes the FULL prompt as `keywords`, and the
old heuristic picked the first uppercase token ("RCA") instead of the equipment tag ("P-101A"),
and double-filtered tag+canonical (ANDed, opposite case) — both yielding zero candidates and an
IndexError in planning. These pin the corrected behavior against a tag-pattern-aware stub host.
"""
from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

from rca_agents.mcp_toolbox import McpToolBox, _tag_tokens

CID = "asset:refinery-gc:unit-101:p-101a"
REF_ID = "0190d3c9-0000-7000-8000-000000000abc"


def test_tag_tokens_extracts_equipment_tag_not_uppercase_words():
    toks = _tag_tokens("RCA on P-101A seal leak")
    assert "P-101A" in toks
    assert "RCA" not in toks            # uppercase word with no digits is not a tag


def test_tag_tokens_uppercases_and_handles_lowercase_input():
    assert _tag_tokens("rca on p-101a") == ["P-101A"]


def _prov():
    return {"tool_name": "asset.search", "tool_version": "v1", "source": "mar",
            "connection_id": None, "source_query": "q", "queried_at": "2026-03-30T12:00:00+00:00",
            "response_id": REF_ID, "record_count": 0, "truncated": False, "raw_tags": [],
            "notes": None}


@pytest.fixture
def host() -> FastMCP:
    """asset.search that honors tag_pattern like the real MAR repo (case-sensitive LIKE on tag)."""
    h = FastMCP("search-stub")
    assets = [{"canonical_id": CID, "tag": "P-101A"},
              {"canonical_id": "asset:refinery-gc:unit-201:p-103a", "tag": "P-103A"}]

    @h.tool(name="asset.search")
    async def search(request: dict):
        tp = request.get("tag_pattern")
        if tp:
            needle = tp.strip("%")
            rows = [a for a in assets if needle in a["tag"]]
        else:
            rows = list(assets)            # no filter -> all (the fallback path)
        return {"data": rows, "provenance": _prov(), "error": None}

    return h


@pytest.mark.asyncio
async def test_search_finds_asset_by_tag_token_from_full_prompt(host):
    async with Client(host) as client:
        tb = McpToolBox(client)
        out = await tb.search_assets("RCA on P-101A seal leak", "refinery-gc")
    assert len(out) == 1 and out[0]["canonical_id"] == CID
    assert out[0]["confidence"] > 0.5      # exact-ish match -> high confidence


@pytest.mark.asyncio
async def test_search_falls_back_to_all_assets_when_no_tag_match(host):
    async with Client(host) as client:
        tb = McpToolBox(client)
        out = await tb.search_assets("investigate the seal leak", "refinery-gc")  # no tag token
    # fallback returns the plant's assets so the LLM always has a shortlist to resolve from
    assert {o["canonical_id"] for o in out} == {
        CID, "asset:refinery-gc:unit-201:p-103a"}
