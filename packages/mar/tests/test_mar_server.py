import json
from pathlib import Path
from uuid import UUID, uuid4

from fastmcp import Client
from rca_contracts import AssetDescriptor, ResolveAssetOutput, ToolResponse

from rca_mar.repository import InMemoryRepository
from rca_mar.seed import seed_from_register
from rca_mar.server import make_mar_mcp

REGISTER = Path(__file__).resolve().parents[1] / "seed_data" / "refplant_assets.yaml"
TENANT = UUID("0190d3c9-0000-7000-8000-0000000000ff")
P101A = UUID("0190d3c9-0000-7000-8000-000000000001")
P101A_CANONICAL = "asset:refinery-gc:unit-101:p-101a"


def _parse(result, model):
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[model].model_validate_json(json.dumps(payload))


async def _client():
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    return Client(make_mar_mcp(repo=repo, tenant_id=TENANT))


async def test_resolve_exact_returns_canonical_id():
    async with await _client() as c:
        res = await c.call_tool("assets.resolve",
                                {"request": {"external_id": "CRDU-P101A", "source_system": "maximo"}})
        resp = _parse(res, ResolveAssetOutput)
        assert resp.error is None and resp.data.status == "resolved"
        assert str(resp.data.asset.asset_id) == str(P101A)
        assert resp.data.canonical_id == P101A_CANONICAL
        assert resp.data.mapping_source == "exact_match"
        assert resp.provenance.record_count == 1


async def test_resolve_unknown_is_success_unresolved():
    async with await _client() as c:
        res = await c.call_tool("assets.resolve",
                                {"request": {"external_id": "ZZZ", "source_system": "sap_pm"}})
        resp = _parse(res, ResolveAssetOutput)
        assert resp.error is None and resp.data.status == "unresolved"
        assert resp.data.asset is None and resp.data.canonical_id is None


async def test_resolve_env_threshold_honored(monkeypatch):
    # crosswalk confidence 0.85: below the 0.92 default -> unresolved; lowering the env
    # threshold (read per request) flips it to resolved without a request override
    async with await _client() as c:
        res = _parse(await c.call_tool("assets.resolve",
                                       {"request": {"external_id": "CRDU-P101A",
                                                    "source_system": "pi_af"}}),
                     ResolveAssetOutput)
        assert res.error is None and res.data.status == "unresolved"
    monkeypatch.setenv("MAR_AUTO_ACCEPT_THRESHOLD", "0.8")
    async with await _client() as c:
        res = _parse(await c.call_tool("assets.resolve",
                                       {"request": {"external_id": "CRDU-P101A",
                                                    "source_system": "pi_af"}}),
                     ResolveAssetOutput)
        assert res.error is None and res.data.status == "resolved"
        assert res.data.canonical_id == P101A_CANONICAL


async def test_resolve_explicit_min_confidence_overrides_env(monkeypatch):
    monkeypatch.setenv("MAR_AUTO_ACCEPT_THRESHOLD", "0.99")
    async with await _client() as c:
        res = _parse(await c.call_tool("assets.resolve",
                                       {"request": {"external_id": "CRDU-P101A",
                                                    "source_system": "pi_af",
                                                    "min_confidence": 0.8}}),
                     ResolveAssetOutput)
        assert res.error is None and res.data.status == "resolved"


async def test_get_by_asset_id_found_and_not_found():
    async with await _client() as c:
        ok = _parse(await c.call_tool("assets.get", {"request": {"asset_id": str(P101A)}}),
                    AssetDescriptor)
        assert ok.error is None and ok.data.tag == "P-101A"
        assert ok.data.canonical_id == P101A_CANONICAL
        miss = _parse(await c.call_tool("assets.get", {"request": {"asset_id": str(uuid4())}}),
                      AssetDescriptor)
        assert miss.data is None and miss.error is not None and miss.error.code == "not_found"


async def test_get_by_canonical_id():
    async with await _client() as c:
        ok = _parse(await c.call_tool("assets.get",
                                      {"request": {"canonical_id": P101A_CANONICAL}}),
                    AssetDescriptor)
        assert ok.error is None and str(ok.data.asset_id) == str(P101A)
        miss = _parse(await c.call_tool("assets.get",
                                        {"request": {"canonical_id": "asset:nope:u:x"}}),
                      AssetDescriptor)
        assert miss.error is not None and miss.error.code == "not_found"


async def test_get_requires_exactly_one_key():
    async with await _client() as c:
        both = _parse(await c.call_tool("assets.get",
                                        {"request": {"asset_id": str(P101A),
                                                     "canonical_id": P101A_CANONICAL}}),
                      AssetDescriptor)
        assert both.error is not None and both.error.code == "validation_failed"
        neither = _parse(await c.call_tool("assets.get", {"request": {}}), AssetDescriptor)
        assert neither.error is not None and neither.error.code == "validation_failed"


async def test_search_by_class():
    async with await _client() as c:
        res = _parse(await c.call_tool(
            "assets.search", {"request": {"iso14224_class": "pump.centrifugal"}}), list[AssetDescriptor])
        assert res.error is None and all(a.iso14224_class == "pump.centrifugal" for a in res.data)


async def test_search_by_canonical_id_pattern():
    async with await _client() as c:
        res = _parse(await c.call_tool(
            "assets.search",
            {"request": {"canonical_id_pattern": "asset:refinery-gc:unit-101:%"}}),
            list[AssetDescriptor])
        assert res.error is None
        assert {a.canonical_id for a in res.data} == {P101A_CANONICAL}
        res = _parse(await c.call_tool(
            "assets.search",
            {"request": {"canonical_id_pattern": "asset:refinery-gc:unit-201:%"}}),
            list[AssetDescriptor])
        assert res.error is None
        assert {a.canonical_id for a in res.data} == {"asset:refinery-gc:unit-201:p-103a"}


async def test_exposed_tools_are_exactly_resolve_get_search():
    # hierarchy moved to the KG (Sprint 2): MAR exposes no hierarchy tool anymore
    async with await _client() as c:
        tools = {t.name for t in await c.list_tools()}
        assert tools == {"assets.resolve", "assets.get", "assets.search"}
