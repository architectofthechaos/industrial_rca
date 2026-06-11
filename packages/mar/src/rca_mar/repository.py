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


class DuplicateActiveConnection(Exception):
    """Raised when activating a connection would give a (plant_id, category) two active
    connections — the one-active-source-per-category invariant (Sprint 2b §1.1, enforced
    by the `uq_connection_active_category` partial unique index in Postgres). The API layer
    catches this and maps it to a 409 category_conflict."""

    def __init__(self, plant_id: str, category: str, existing_connection_id: str) -> None:
        self.plant_id = plant_id
        self.category = category
        self.existing_connection_id = existing_connection_id
        super().__init__(
            f"connection for ({plant_id!r}, {category!r}) already active: "
            f"{existing_connection_id!r}")


@dataclass(frozen=True)
class ConnectionRow:
    """A configured source-system connection (Sprint 2b §1.1); mirrors `models.Connection`."""
    connection_id: str
    plant_id: str
    category: str
    connector_type: str
    display_name: str
    base_url: str
    auth_config: dict[str, Any]
    status: str = "pending"
    extra_config: dict[str, Any] | None = None
    last_tested_at: datetime | None = None
    last_test_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class AliasRow:
    # Invariant: AliasRow omits resolved_at/validated_by/validated_at; it is therefore
    # never used to rewrite human_validated rows (those are protected in resolution.py).
    asset_id: UUID
    tenant_id: UUID
    connection_id: str
    external_id: str
    valid_from: datetime
    valid_to: datetime | None
    mapping_source: str
    confidence: float
    is_primary: bool = False
    # Phase 1 spec §2.3 additions.
    resolution_status: str = "auto_resolved"
    candidate_alternatives: list[dict[str, Any]] | None = None
    resolved_by: str | None = None
    vendor_path: str | None = None
    vendor_metadata: dict[str, Any] | None = None
    confirmed_by: str | None = None
    notes: str | None = None


@runtime_checkable
class AssetRepository(Protocol):
    async def find_active_alias(self, tenant: UUID, connection_id: str, external_id: str,
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
    async def source_handle_for(self, tenant: UUID, asset_id: UUID,
                                connection_id: str) -> str | None: ...
    async def upsert_unresolved(self, tenant: UUID, source: str, external_id: str,
                                payload: dict[str, Any] | None) -> None: ...
    async def upsert_asset(self, asset: AssetDescriptor) -> None: ...
    async def upsert_alias(self, alias: AliasRow) -> None: ...
    # Connection CRUD (Sprint 2b §1.1).
    async def upsert_connection(self, conn: ConnectionRow) -> None: ...
    async def get_connection(self, connection_id: str) -> ConnectionRow | None: ...
    async def list_connections(self, *, plant_id: str | None = None, category: str | None = None,
                               status: str | None = None) -> list[ConnectionRow]: ...
    async def delete_connection(self, connection_id: str) -> None: ...
    async def count_aliases_for_connection(self, connection_id: str) -> int: ...


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
        self.connections: dict[str, ConnectionRow] = {}

    async def upsert_asset(self, asset: AssetDescriptor) -> None:
        self.assets[(asset.tenant_id, asset.asset_id)] = asset

    async def upsert_alias(self, alias: AliasRow) -> None:
        # Mirror PostgresRepository.upsert_alias: CLOSE the previous active row
        # (valid_to = new row's valid_from) instead of deleting it, so historical
        # valid_at lookups keep resolving to the alias that was valid at that time.
        self.aliases = [
            replace(a, valid_to=alias.valid_from)
            if (a.tenant_id == alias.tenant_id
                and a.connection_id == alias.connection_id
                and a.external_id == alias.external_id
                and a.valid_to is None)
            else a
            for a in self.aliases]
        self.aliases.append(alias)

    async def find_active_alias(self, tenant, connection_id, external_id, *, valid_at):
        for a in self.aliases:
            if (a.tenant_id == tenant and a.connection_id == connection_id
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

    async def source_handle_for(self, tenant, asset_id, connection_id):
        for a in self.aliases:
            if (a.tenant_id == tenant and a.asset_id == asset_id
                    and a.connection_id == connection_id and a.valid_to is None):
                return a.external_id
        return None

    async def upsert_unresolved(self, tenant, source, external_id, payload):
        key = (tenant, source, external_id)
        row = self.unresolved.get(key)
        if row:
            row["occurrence_count"] += 1
        else:
            self.unresolved[key] = {"occurrence_count": 1, "candidate_payload": payload}

    async def upsert_connection(self, conn: ConnectionRow) -> None:
        # Enforce the one-active-per-(plant, category) invariant (the partial unique index
        # in Postgres) so hermetic tests catch a conflict the same way the live DB would.
        if conn.status == "active":
            for existing in self.connections.values():
                if (existing.connection_id != conn.connection_id
                        and existing.plant_id == conn.plant_id
                        and existing.category == conn.category
                        and existing.status == "active"):
                    raise DuplicateActiveConnection(
                        conn.plant_id, conn.category, existing.connection_id)
        self.connections[conn.connection_id] = conn

    async def get_connection(self, connection_id: str) -> ConnectionRow | None:
        return self.connections.get(connection_id)

    async def list_connections(self, *, plant_id=None, category=None, status=None):
        return [c for c in self.connections.values()
                if (plant_id is None or c.plant_id == plant_id)
                and (category is None or c.category == category)
                and (status is None or c.status == status)]

    async def delete_connection(self, connection_id: str) -> None:
        self.connections.pop(connection_id, None)

    async def count_aliases_for_connection(self, connection_id: str) -> int:
        return sum(1 for a in self.aliases if a.connection_id == connection_id)


__all__ = ["AssetRepository", "AliasRow", "ConnectionRow", "DuplicateActiveConnection",
           "InMemoryRepository"]
