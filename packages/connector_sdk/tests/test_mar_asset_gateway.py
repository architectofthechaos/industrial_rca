"""MarAssetGateway — resolves (canonical_id, category) -> source handle via MAR (G28/D13).

Tests are hermetic: a minimal FakeRepo stands in for AssetRepository, shaped to the real
signatures (find_asset_by_canonical_id, list_connections, source_handle_for). asyncio_mode
is "auto" in the workspace root, so plain async def tests run without any decorator.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from rca_connector_sdk import NotFound
from rca_connector_sdk.assets import MarAssetGateway

# ── fixtures ──────────────────────────────────────────────────────────────────

CANONICAL = "asset:refinery-gc:unit-101:p-101a"
PLANT_ID = "refinery-gc"
TENANT = UUID("00000000-0000-0000-0000-000000000001")
ASSET_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
CONN_ID = "conn-maximo-refinery-gc"
HANDLE = "CRDU-P101A"

_ASSET = SimpleNamespace(asset_id=ASSET_ID, canonical_id=CANONICAL)
_CONNECTION = SimpleNamespace(connection_id=CONN_ID, plant_id=PLANT_ID, category="cmms",
                              status="active")


class FakeRepo:
    """Minimal fake implementing only the methods MarAssetGateway calls."""

    def __init__(self, *, asset=_ASSET, connections=None, handle=HANDLE):
        self._asset = asset
        self._connections: list = connections if connections is not None else [_CONNECTION]
        self._handle = handle

    async def find_asset_by_canonical_id(self, tenant: UUID, canonical_id: str):
        return self._asset if (self._asset is not None
                               and self._asset.canonical_id == canonical_id) else None

    async def list_connections(self, *, plant_id=None, category=None, status=None):
        return [
            c for c in self._connections
            if (plant_id is None or c.plant_id == plant_id)
            and (category is None or c.category == category)
            and (status is None or c.status == status)
        ]

    async def source_handle_for(self, tenant: UUID, asset_id: UUID, connection_id: str):
        if asset_id == ASSET_ID and connection_id == CONN_ID:
            return self._handle
        return None


# ── test cases ────────────────────────────────────────────────────────────────

async def test_resolves_cmms_location():
    """Happy path: canonical_id + active cmms connection + alias -> Maximo location."""
    gw = MarAssetGateway(repo=FakeRepo(), tenant_id=TENANT)
    result = await gw.source_handle(CANONICAL, "cmms")
    assert result == HANDLE


async def test_unmapped_asset_raises_not_found():
    """find_asset_by_canonical_id returns None -> NotFound (not a silent empty)."""
    gw = MarAssetGateway(repo=FakeRepo(asset=None), tenant_id=TENANT)
    with pytest.raises(NotFound, match="no MAR asset"):
        await gw.source_handle(CANONICAL, "cmms")


async def test_no_active_connection_raises_not_found():
    """No active cmms connection for plant -> NotFound."""
    inactive = SimpleNamespace(connection_id=CONN_ID, plant_id=PLANT_ID,
                               category="cmms", status="pending")
    gw = MarAssetGateway(repo=FakeRepo(connections=[inactive]), tenant_id=TENANT)
    with pytest.raises(NotFound, match="no active .cmms. connection"):
        await gw.source_handle(CANONICAL, "cmms")


async def test_alias_missing_raises_not_found():
    """source_handle_for returns None -> NotFound."""
    gw = MarAssetGateway(repo=FakeRepo(handle=None), tenant_id=TENANT)
    with pytest.raises(NotFound, match="no .cmms. source handle"):
        await gw.source_handle(CANONICAL, "cmms")


async def test_tag_for_inherited_from_canonical_slug():
    """MarAssetGateway inherits tag_for from CanonicalSlugAssetGateway."""
    gw = MarAssetGateway(repo=FakeRepo(), tenant_id=TENANT)
    assert await gw.tag_for(CANONICAL) == "P-101A"
