"""MarResolver — implements connector_sdk's SignalResolver port for asset-scoped connectors.

Backs source_binding(asset_id, source) from the registry; signal-level resolution belongs to
TRS, so resolve(signal_id) raises. The composition layer injects this into connector factories.
"""
from __future__ import annotations

from uuid import UUID

from rca_connector_sdk import SourceBinding
from rca_connector_sdk.errors import UnresolvedSignal
from rca_contracts import SignalDescriptor

from .repository import AssetRepository


class MarResolver:
    def __init__(self, *, repo: AssetRepository, tenant_id: UUID) -> None:
        self._repo = repo
        self._tenant = tenant_id

    async def resolve(self, signal_id: UUID) -> SignalDescriptor:
        raise UnresolvedSignal(
            "MAR resolves assets, not signals; signal resolution is TRS's domain (EPIC-003)")

    async def source_binding(self, entity_id: UUID, source: str) -> SourceBinding:
        handle = await self._repo.source_handle_for(self._tenant, entity_id, source)
        if handle is None:
            raise UnresolvedSignal(f"no {source!r} alias for asset {entity_id} in MAR")
        return SourceBinding(handle=handle, raw_unit="n/a")


__all__ = ["MarResolver"]
