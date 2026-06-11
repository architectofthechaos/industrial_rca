"""MarResolver — implements connector_sdk's TagResolver port for asset-scoped connectors.

Backs source_binding(asset_id, source) from the registry; tag-level resolution belongs to
the onboarding pipeline, so resolve(entity_id) raises. The composition layer injects this
into connector factories.
"""
from __future__ import annotations

from uuid import UUID

from rca_connector_sdk import SourceBinding
from rca_connector_sdk.errors import UnresolvedSignal
from rca_contracts import TagDescriptor

from .repository import AssetRepository


class MarResolver:
    def __init__(self, *, repo: AssetRepository, tenant_id: UUID) -> None:
        self._repo = repo
        self._tenant = tenant_id

    async def resolve(self, entity_id: UUID) -> TagDescriptor:
        raise UnresolvedSignal(
            "MAR resolves assets, not tags; tag resolution is the onboarding pipeline's "
            "domain (EPIC-003)")

    async def source_binding(self, entity_id: UUID, source: str) -> SourceBinding:
        handle = await self._repo.source_handle_for(self._tenant, entity_id, source)
        if handle is None:
            raise UnresolvedSignal(f"no {source!r} alias for asset {entity_id} in MAR")
        return SourceBinding(handle=handle, raw_unit="n/a")


__all__ = ["MarResolver"]
