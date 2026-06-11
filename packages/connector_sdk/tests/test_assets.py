"""AssetGateway implementations (promoted to the SDK in Sprint 2b Track 3 Task 5).

StaticAssetGateway: hit/miss for both tag_for and source_handle.
CanonicalSlugAssetGateway: tag_for derives from the name slug; source_handle has no rule.
"""
import pytest

from rca_connector_sdk import (
    CanonicalSlugAssetGateway,
    NotFound,
    StaticAssetGateway,
)

CANONICAL = "asset:refinery-gc:unit-101:p-101a"


async def test_static_gateway_tag_hit_and_miss():
    gw = StaticAssetGateway(tags={CANONICAL: "P-101A"})
    assert await gw.tag_for(CANONICAL) == "P-101A"
    with pytest.raises(NotFound):
        await gw.tag_for("asset:refinery-gc:unit-101:does-not-exist")


async def test_static_gateway_source_handle_hit_and_miss():
    gw = StaticAssetGateway(handles={(CANONICAL, "cmms"): "CRDU-P101A"})
    assert await gw.source_handle(CANONICAL, "cmms") == "CRDU-P101A"
    # wrong category misses
    with pytest.raises(NotFound):
        await gw.source_handle(CANONICAL, "document")
    # wrong canonical_id misses
    with pytest.raises(NotFound):
        await gw.source_handle("asset:refinery-gc:unit-101:p-999z", "cmms")


async def test_canonical_slug_gateway_tag_for_uppercases_slug():
    gw = CanonicalSlugAssetGateway()
    assert await gw.tag_for(CANONICAL) == "P-101A"


async def test_canonical_slug_gateway_tag_for_rejects_malformed():
    gw = CanonicalSlugAssetGateway()
    with pytest.raises(ValueError):
        await gw.tag_for("not-a-canonical-id")


async def test_canonical_slug_gateway_source_handle_raises_not_found():
    gw = CanonicalSlugAssetGateway()
    with pytest.raises(NotFound):
        await gw.source_handle(CANONICAL, "cmms")
