"""SQLAlchemy 2.0 ORM models for the MAR tables (SPEC-011, Phase 1 spec §2.1–§2.3).

Dual-key identity: `assets.asset_id` (UUID PK) + `assets.canonical_id`
(TEXT UNIQUE, `asset:{plant}:{unit}:{name}`). Hierarchy (the old parent
self-FK) moved to the knowledge graph in Sprint 2 and no longer exists here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Connection(Base):
    """A configured source-system connection (Sprint 2b §1.1).

    `connection_id` is a human-readable PK `{plant_id}.{category}.{name}`
    (e.g. `refinery-gc.hierarchy.pi-af-default`). `category` is one of
    hierarchy / historian / cmms / document / operator_log (enforced in the app
    layer, stored TEXT). At most one row per `(plant_id, category)` may be
    `status='active'` — enforced by the partial unique index
    `uq_connection_active_category`. Aliases FK their owning connection here, so
    each alias's category and routing live on the connection, not the alias.
    """

    __tablename__ = "connections"
    connection_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    connector_type: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending",
                                        server_default="pending")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=_utcnow, onupdate=_utcnow,
                                                 server_default=func.now())

    __table_args__ = (
        Index("uq_connection_active_category", "plant_id", "category",
              unique=True, postgresql_where=text("status = 'active'")),
    )


class Asset(Base):
    """Canonical asset registry row.

    `status` is the authoritative lifecycle field ('active' | 'decommissioned' |
    'pending_review'); `decommissioned_at` only records the moment of transition.
    `plant_id` is the human-facing scope used inside canonical_id and coexists
    with the `tenant_id` UUID. `attributes` holds class-specific fields; the
    typed columns (manufacturer, model, ...) stay.
    """

    __tablename__ = "assets"
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    canonical_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    plant_id: Mapped[str] = mapped_column(Text, nullable=False)
    iso14224_class: Mapped[str] = mapped_column(String, nullable=False)
    iso14224_level: Mapped[int] = mapped_column(Integer, nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False)
    service: Mapped[str | None] = mapped_column(String, nullable=True)
    criticality: Mapped[str] = mapped_column(String(1), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active",
                                        server_default="active")
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String, nullable=True)
    commissioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decommissioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=_utcnow, onupdate=_utcnow,
                                                 server_default=func.now())


class AssetAlias(Base):
    """External-id binding for an asset (Phase 1 spec §2.3).

    Column-name mapping to the spec: `confidence` is the spec's
    `resolution_confidence` and `mapping_source` is the spec's
    `resolution_method` ('authoritative_import', 'exact_match',
    'rule:<id>' — a pattern_rules.yaml rule id such as 'rule:pump_p_tag' —
    'cross_walk', 'manual', 'llm_v<n>'). They keep their
    original names for backwards compatibility.

    Pending-review semantics (Sprint 1): when automated resolution finds a
    single best candidate below the auto-accept threshold, a row is written
    with resolution_status='pending_review' bound to that candidate, with
    `candidate_alternatives` holding every candidate considered
    ([{"canonical_id", "confidence", "method"}]). When there is no candidate
    (or multiple equally-scored crosswalk candidates, where no primary binding
    is defensible), the deprecated asset_aliases_unresolved flow is used
    instead.
    """

    __tablename__ = "asset_aliases"
    alias_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assets.asset_id"), nullable=False, index=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        Text, ForeignKey("connections.connection_id"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    vendor_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mapping_source: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False, default="auto_resolved",
                                                   server_default="auto_resolved")
    candidate_alternatives: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                  default=_utcnow, server_default=func.now())
    validated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_alias_lookup", "tenant_id", "connection_id", "external_id"),
        Index("uq_alias_active", "tenant_id", "connection_id", "external_id",
              unique=True, postgresql_where=text("valid_to IS NULL")),
    )


class AssetAliasUnresolved(Base):
    # DEPRECATED: Sprint 3 will replace with resolution_status='pending_review' on
    # asset_aliases. Kept for backwards compat with existing tests until Sprint 3.
    __tablename__ = "asset_aliases_unresolved"
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_system: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurrence_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class OnboardingRun(Base):
    """Persistent run record for a Temporal OnboardingWorkflow execution (Sprint 2b §2.5).

    The workflow writes a row at start (status='running') and updates it when the
    workflow terminates (status='completed' | 'failed' | 'cancelled'). The onboarding
    package uses the MAR engine/session directly so that onboarding_runs stays in the
    same Alembic migration chain as connections and asset_aliases.

    `connection_ids` is the list of connection_id strings that were requested for this
    run (null = all active connections for the plant at run time).
    `per_category_results` maps each category to a short result string
    (e.g. 'ok', 'skipped:connection_unhealthy').
    `counts` holds aggregate numeric results:
        {assets_new, assets_updated, assets_decommissioned,
         bindings_pending_review, hierarchy_nodes_upserted}.
    `errors` is a list of structured error dicts.
    """

    __tablename__ = "onboarding_runs"
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    plant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # list of connection_id strings; null = all active for the plant
    connection_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # running / completed / failed / cancelled
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    per_category_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_onboarding_runs_plant_status", "plant_id", "status"),
    )
