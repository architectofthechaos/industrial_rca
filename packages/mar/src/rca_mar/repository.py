"""AssetRepository Protocol + an in-memory implementation for hermetic tests.

The Postgres implementation lives in repository_pg.py; both satisfy this Protocol so
resolution/tools/resolver are tested without a database and run against Postgres in prod.

AliasRow field-name mapping to the Phase 1 spec: `confidence` == spec
`resolution_confidence`, `mapping_source` == spec `resolution_method`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from rca_contracts import AssetDescriptor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvalidTransition(Exception):
    """An illegal resolution_status transition on an asset_aliases row (Sprint 2b §4.1).

    The Resolution Queue write paths (validate/reject/supersede) refuse to move a binding out
    of a terminal state — `rejected` and `superseded` rows cannot be re-opened (the correct
    move is to create a NEW binding). The API layer maps this to a 409. This is distinct from
    the connections-status `InvalidTransition` in connections_api.state_machine.
    """

    def __init__(self, alias_id: UUID, current: str, target: str) -> None:
        self.alias_id = alias_id
        self.current = current
        self.target = target
        super().__init__(
            f"alias {alias_id} cannot transition {current!r} -> {target!r}")


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
    # Resolution Queue fields (Sprint 2b §4.1). The auto-resolver path (resolution.py) never
    # sets validated_by/validated_at — only the human review write paths do, so an auto path
    # can never forge a human_validated provenance. `alias_id` is None for rows the resolver
    # constructs (the repo mints one on upsert); it is populated on rows read back from the
    # store so the write paths can address a specific binding by id.
    alias_id: UUID | None = None
    validated_by: str | None = None
    validated_at: datetime | None = None
    resolved_at: datetime | None = None


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
    # Resolution Queue write paths (Sprint 2b §4.1).
    async def get_alias(self, alias_id: UUID) -> AliasRow | None: ...
    async def validate_binding(self, alias_id: UUID, validated_by: str) -> AliasRow: ...
    async def reject_binding(self, alias_id: UUID, rejected_by: str, reason: str) -> AliasRow: ...
    async def supersede_binding(self, alias_id: UUID, *,
                                superseded_by_alias_id: UUID | None = None,
                                system_initiated: bool = False) -> AliasRow: ...
    async def list_pending_bindings(self, tenant: UUID, *, plant_id: str | None = None,
                                    connection_id: str | None = None,
                                    limit: int = 50) -> list[AliasRow]: ...
    # Onboarding reconcile/decommission (Sprint 2b §2.3).
    async def list_active_aliases_for_connection(
        self, tenant: UUID, connection_id: str) -> list[AliasRow]: ...
    async def decommission_asset(self, tenant: UUID, asset_id: UUID) -> None: ...
    async def resolution_stats(self, tenant: UUID) -> list[dict[str, Any]]: ...
    # Connection CRUD (Sprint 2b §1.1).
    async def upsert_connection(self, conn: ConnectionRow) -> None: ...
    async def get_connection(self, connection_id: str) -> ConnectionRow | None: ...
    async def list_connections(self, *, plant_id: str | None = None, category: str | None = None,
                               status: str | None = None) -> list[ConnectionRow]: ...
    async def delete_connection(self, connection_id: str) -> None: ...
    async def count_aliases_for_connection(self, connection_id: str) -> int: ...
    # Document-embedding cache (Sprint 6 WI4): content-addressed upsert, cosine search,
    # connection-scoped invalidation. The gather leg retrieves docs by query embedding.
    async def upsert_document_embedding(self, *, content_hash: str, model: str, document_id: str,
                                        doc_type: str | None, description: str | None,
                                        embedding: list[float], connection_id: str) -> None: ...
    async def search_document_embeddings(self, *, connection_id: str,
                                         query_embedding: list[float], top: int = 5,
                                         doc_types: list[str] | None = None) -> list[dict]: ...
    async def delete_document_embeddings_for_connection(self, connection_id: str) -> None: ...


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
        # AssetDescriptor (the canonical contract) carries decommissioned_at but NOT the
        # lifecycle `status` column (that lives on the Asset ORM row). Track status here so
        # the in-memory repo mirrors the PG `assets.status` field for decommission tests;
        # defaults to "active" for any asset not explicitly decommissioned.
        self.asset_status: dict[tuple[UUID, UUID], str] = {}
        # Every upsert_asset/upsert_alias/decommission_asset call bumps this; the onboarding
        # idempotency test asserts a no-change re-run leaves it untouched (the zero-row-write
        # guarantee — the activity must skip the write entirely, not write the same value back).
        self.write_count = 0
        # Document-embedding cache (Sprint 6 WI4). Each row mirrors the document_embeddings
        # table; keyed for upsert by (content_hash, model). Python cosine keeps the hermetic
        # MCP-server test DB-free.
        self._doc_embeddings: list[dict[str, Any]] = []

    async def upsert_asset(self, asset: AssetDescriptor) -> None:
        self.write_count += 1
        self.assets[(asset.tenant_id, asset.asset_id)] = asset

    async def upsert_alias(self, alias: AliasRow) -> None:
        self.write_count += 1
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
        # The PG row always has an alias_id PK and a resolved_at; mint them here so a row read
        # back via get_alias is addressable by id (matching the live DB).
        stored = replace(
            alias,
            alias_id=alias.alias_id or uuid4(),
            resolved_at=alias.resolved_at or _utcnow())
        self.aliases.append(stored)

    def _get_alias_index(self, alias_id: UUID) -> int | None:
        for i, a in enumerate(self.aliases):
            if a.alias_id == alias_id:
                return i
        return None

    async def get_alias(self, alias_id: UUID) -> AliasRow | None:
        i = self._get_alias_index(alias_id)
        return self.aliases[i] if i is not None else None

    async def validate_binding(self, alias_id: UUID, validated_by: str) -> AliasRow:
        i = self._get_alias_index(alias_id)
        if i is None:
            raise KeyError(alias_id)
        row = self.aliases[i]
        if row.resolution_status == "human_validated":
            return row  # idempotent: re-validating an already-validated row is a no-op
        if row.resolution_status in ("rejected", "superseded"):
            raise InvalidTransition(alias_id, row.resolution_status, "human_validated")
        updated = replace(row, resolution_status="human_validated",
                          validated_by=validated_by, validated_at=_utcnow())
        self.aliases[i] = updated
        return updated

    async def reject_binding(self, alias_id: UUID, rejected_by: str, reason: str) -> AliasRow:
        i = self._get_alias_index(alias_id)
        if i is None:
            raise KeyError(alias_id)
        row = self.aliases[i]
        now = _utcnow()
        if row.resolution_status == "rejected":
            return row  # idempotent re-reject: leave the original stamp/notes untouched
        if row.resolution_status == "human_validated":
            raise InvalidTransition(alias_id, row.resolution_status, "rejected")
        note = f"rejected: {reason}"
        notes = f"{row.notes}\n{note}" if row.notes else note
        updated = replace(row, resolution_status="rejected", valid_to=row.valid_to or now,
                          validated_by=rejected_by, validated_at=now, notes=notes)
        self.aliases[i] = updated
        return updated

    async def supersede_binding(self, alias_id: UUID, *,
                                superseded_by_alias_id: UUID | None = None,
                                system_initiated: bool = False) -> AliasRow:
        i = self._get_alias_index(alias_id)
        if i is None:
            raise KeyError(alias_id)
        row = self.aliases[i]
        now = _utcnow()
        if row.resolution_status == "superseded":
            return row  # idempotent
        by = "system" if system_initiated else "review"
        note = (f"superseded by {superseded_by_alias_id} ({by})"
                if superseded_by_alias_id else f"superseded ({by})")
        notes = f"{row.notes}\n{note}" if row.notes else note
        updated = replace(row, resolution_status="superseded", valid_to=row.valid_to or now,
                          notes=notes)
        self.aliases[i] = updated
        return updated

    async def list_active_aliases_for_connection(self, tenant, connection_id):
        # Active == open-ended (valid_to IS NULL); mirrors find_active_alias(valid_at=None).
        return [a for a in self.aliases
                if a.tenant_id == tenant and a.connection_id == connection_id
                and a.valid_to is None]

    async def decommission_asset(self, tenant, asset_id):
        asset = self.assets.get((tenant, asset_id))
        if asset is None:
            return
        self.write_count += 1
        self.asset_status[(tenant, asset_id)] = "decommissioned"
        self.assets[(tenant, asset_id)] = asset.model_copy(
            update={"decommissioned_at": _utcnow()})

    def status_of(self, tenant: UUID, asset_id: UUID) -> str:
        """Lifecycle status mirror for the assets row (tests assert decommission flips it)."""
        return self.asset_status.get((tenant, asset_id), "active")

    async def list_pending_bindings(self, tenant, *, plant_id=None, connection_id=None, limit=50):
        out: list[AliasRow] = []
        for a in self.aliases:
            if a.tenant_id != tenant or a.resolution_status != "pending_review":
                continue
            if a.valid_to is not None:
                continue
            if connection_id is not None and a.connection_id != connection_id:
                continue
            if plant_id is not None:
                asset = self.assets.get((tenant, a.asset_id))
                if asset is None or asset.plant_id != plant_id:
                    continue
            out.append(a)
            if len(out) >= limit:
                break
        return out

    async def resolution_stats(self, tenant):
        counts: dict[tuple[str, str], int] = {}
        for a in self.aliases:
            if a.tenant_id != tenant:
                continue
            key = (a.connection_id, a.resolution_status)
            counts[key] = counts.get(key, 0) + 1
        return [{"connection_id": cid, "resolution_status": status, "count": n}
                for (cid, status), n in sorted(counts.items())]

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

    # ---- Document-embedding cache (Sprint 6 WI4) ----
    async def upsert_document_embedding(self, *, content_hash, model, document_id, doc_type,
                                        description, embedding, connection_id) -> None:
        row = {"content_hash": content_hash, "model": model, "document_id": document_id,
               "doc_type": doc_type, "description": description, "embedding": list(embedding),
               "connection_id": connection_id}
        for i, r in enumerate(self._doc_embeddings):
            if r["content_hash"] == content_hash and r["model"] == model:
                self._doc_embeddings[i] = row  # upsert by (content_hash, model)
                return
        self._doc_embeddings.append(row)

    async def search_document_embeddings(self, *, connection_id, query_embedding, top=5,
                                         doc_types=None) -> list[dict]:
        qnorm = sum(x * x for x in query_embedding) ** 0.5
        scored: list[tuple[float, dict[str, Any]]] = []
        for r in self._doc_embeddings:
            if r["connection_id"] != connection_id:
                continue
            if doc_types and r["doc_type"] not in doc_types:
                continue
            v = r["embedding"]
            vnorm = sum(x * x for x in v) ** 0.5
            denom = qnorm * vnorm
            # zero-norm guard: an all-zero embedding has no direction -> cosine undefined; score 0.
            cosine = (sum(a * b for a, b in zip(query_embedding, v)) / denom) if denom else 0.0
            scored.append((cosine, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [{"document_id": r["document_id"], "doc_type": r["doc_type"],
                 "description": r["description"], "score": score}
                for score, r in scored[:top]]

    async def delete_document_embeddings_for_connection(self, connection_id) -> None:
        self._doc_embeddings = [r for r in self._doc_embeddings
                                if r["connection_id"] != connection_id]


__all__ = ["AssetRepository", "AliasRow", "ConnectionRow", "DuplicateActiveConnection",
           "InvalidTransition", "InMemoryRepository"]
