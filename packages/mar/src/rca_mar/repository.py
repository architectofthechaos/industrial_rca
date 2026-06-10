"""AssetRepository Protocol + an in-memory implementation for hermetic tests.

The Postgres implementation lives in repository_pg.py; both satisfy this Protocol so
resolution/tools/resolver are tested without a database and run against Postgres in prod.

AliasRow field-name mapping to the Phase 1 spec: `confidence` == spec
`resolution_confidence`, `mapping_source` == spec `resolution_method`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from rca_contracts import AssetDescriptor


@dataclass(frozen=True)
class AliasRow:
    # Invariant: AliasRow omits resolved_at/validated_by/validated_at; it is therefore
    # never used to rewrite human_validated rows (those are protected in resolution.py).
    asset_id: UUID
    tenant_id: UUID
    source_system: str
    external_id: str
    valid_from: datetime
    valid_to: datetime | None
    mapping_source: str
    confidence: float
    is_primary: bool = False
    # Phase 1 spec §2.3 additions. source_system_type defaults to 'cmms' purely for
    # test-fixture convenience; production write paths (seed, resolution) always set it.
    source_system_type: str = "cmms"
    resolution_status: str = "auto_resolved"
    candidate_alternatives: list[dict[str, Any]] | None = None
    resolved_by: str | None = None
    vendor_path: str | None = None
    vendor_metadata: dict[str, Any] | None = None
    confirmed_by: str | None = None
    notes: str | None = None


@runtime_checkable
class AssetRepository(Protocol):
    async def find_active_alias(self, tenant: UUID, source: str, external_id: str,
                                *, valid_at: datetime | None) -> AliasRow | None: ...
    async def find_crosswalk_candidates(self, tenant: UUID, external_id: str) -> list[AliasRow]: ...
    async def find_asset_by_tag(self, tenant: UUID, tag: str) -> AssetDescriptor | None: ...
    async def find_asset_by_canonical_id(self, tenant: UUID,
                                         canonical_id: str) -> AssetDescriptor | None: ...
    async def get_asset(self, tenant: UUID, asset_id: UUID) -> AssetDescriptor | None: ...
    async def search_assets(self, tenant: UUID, *, iso14224_class: str | None = None,
                            tag_pattern: str | None = None,
                            canonical_id_pattern: str | None = None,
                            criticality: list[str] | None = None, service: str | None = None,
                            limit: int = 50) -> list[AssetDescriptor]: ...
    async def source_handle_for(self, tenant: UUID, asset_id: UUID, source: str) -> str | None: ...
    async def upsert_unresolved(self, tenant: UUID, source: str, external_id: str,
                                payload: dict[str, Any] | None) -> None: ...
    async def upsert_asset(self, asset: AssetDescriptor) -> None: ...
    async def upsert_alias(self, alias: AliasRow) -> None: ...


def _like_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a SQL LIKE pattern to an anchored regex (parity with PG's `LIKE`):
    '%' -> '.*', '_' -> '.', everything else escaped; used with fullmatch.
    Note: PG LIKE escape sequences (e.g. `\\%` to match a literal percent) are NOT supported."""
    return re.compile(
        "".join(".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern),
        re.DOTALL)


def _active(alias: AliasRow, valid_at: datetime | None) -> bool:
    # Mirror PostgresRepository.find_active_alias exactly (keeps the two repos in lockstep):
    #   valid_at is None  -> only open-ended rows (valid_to IS NULL) count as active.
    #   valid_at given     -> valid_from <= valid_at AND (valid_to IS NULL OR valid_at < valid_to).
    if valid_at is None:
        return alias.valid_to is None
    if alias.valid_from > valid_at:
        return False
    return alias.valid_to is None or valid_at < alias.valid_to


class InMemoryRepository:
    def __init__(self) -> None:
        self.assets: dict[tuple[UUID, UUID], AssetDescriptor] = {}
        self.aliases: list[AliasRow] = []
        self.unresolved: dict[tuple[UUID, str, str], dict[str, Any]] = {}

    async def upsert_asset(self, asset: AssetDescriptor) -> None:
        self.assets[(asset.tenant_id, asset.asset_id)] = asset

    async def upsert_alias(self, alias: AliasRow) -> None:
        # Mirror PostgresRepository.upsert_alias: CLOSE the previous active row
        # (valid_to = new row's valid_from) instead of deleting it, so historical
        # valid_at lookups keep resolving to the alias that was valid at that time.
        self.aliases = [
            replace(a, valid_to=alias.valid_from)
            if (a.tenant_id == alias.tenant_id
                and a.source_system == alias.source_system
                and a.external_id == alias.external_id
                and a.valid_to is None)
            else a
            for a in self.aliases]
        self.aliases.append(alias)

    async def find_active_alias(self, tenant, source, external_id, *, valid_at):
        for a in self.aliases:
            if (a.tenant_id == tenant and a.source_system == source
                    and a.external_id == external_id and _active(a, valid_at)):
                return a
        return None

    async def find_crosswalk_candidates(self, tenant, external_id):
        return [a for a in self.aliases
                if a.tenant_id == tenant and a.external_id == external_id and a.valid_to is None]

    async def find_asset_by_tag(self, tenant, tag):
        for a in self.assets.values():
            if a.tenant_id == tenant and a.tag == tag:
                return a
        return None

    async def find_asset_by_canonical_id(self, tenant, canonical_id):
        for a in self.assets.values():
            if a.tenant_id == tenant and a.canonical_id == canonical_id:
                return a
        return None

    async def get_asset(self, tenant, asset_id):
        return self.assets.get((tenant, asset_id))

    async def search_assets(self, tenant, *, iso14224_class=None, tag_pattern=None,
                            canonical_id_pattern=None, criticality=None, service=None, limit=50):
        out = []
        for a in self.assets.values():
            if a.tenant_id != tenant:
                continue
            if iso14224_class and a.iso14224_class != iso14224_class:
                continue
            # tag_pattern: known pre-existing LIKE-vs-substring divergence from PG; deferred.
            if tag_pattern and tag_pattern.replace("%", "") not in a.tag:
                continue
            if canonical_id_pattern and not _like_to_regex(canonical_id_pattern).fullmatch(
                    a.canonical_id):
                continue
            if criticality and a.criticality not in criticality:
                continue
            if service and a.service != service:
                continue
            out.append(a)
        return out[:limit]

    async def source_handle_for(self, tenant, asset_id, source):
        for a in self.aliases:
            if (a.tenant_id == tenant and a.asset_id == asset_id
                    and a.source_system == source and a.valid_to is None):
                return a.external_id
        return None

    async def upsert_unresolved(self, tenant, source, external_id, payload):
        key = (tenant, source, external_id)
        row = self.unresolved.get(key)
        if row:
            row["occurrence_count"] += 1
        else:
            self.unresolved[key] = {"occurrence_count": 1, "candidate_payload": payload}


__all__ = ["AssetRepository", "AliasRow", "InMemoryRepository"]
