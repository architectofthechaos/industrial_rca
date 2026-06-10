"""Phase 1 spec alignment — dual-key identity + alias resolution metadata (Sprint 1 WI2).

Additive columns on assets/asset_aliases plus the parent_asset_id drop (hierarchy
moves to the KG in Sprint 2). NOT NULL columns that have a natural constant get a
server_default so the migration backfills trivially (there is no production data —
only dev DBs). `assets.canonical_id`, `assets.plant_id` and
`asset_aliases.source_system_type` are added NOT NULL *without* a default:
applying this on a non-empty dev DB will fail by design — recreate the dev DB
(docker compose) instead of backfilling.

Revision ID: 0002_phase1_alignment
Revises: 0001_initial
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_phase1_alignment"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- assets: dual-key identity + lifecycle + audit (spec §2.1) ---
    op.add_column("assets", sa.Column("canonical_id", sa.Text(), nullable=False))
    op.create_unique_constraint("uq_assets_canonical_id", "assets", ["canonical_id"])
    op.add_column("assets", sa.Column("plant_id", sa.Text(), nullable=False))
    op.add_column("assets", sa.Column("status", sa.Text(), nullable=False,
                                      server_default="active"))
    op.add_column("assets", sa.Column("attributes", postgresql.JSONB(), nullable=True))
    op.add_column("assets", sa.Column("created_at", sa.DateTime(timezone=True),
                                      nullable=False, server_default=sa.func.now()))
    op.add_column("assets", sa.Column("updated_at", sa.DateTime(timezone=True),
                                      nullable=False, server_default=sa.func.now()))

    # --- assets: hierarchy leaves MAR (spec §2.2) ---
    op.drop_index("ix_assets_tenant_parent", table_name="assets")
    op.drop_column("assets", "parent_asset_id")

    # --- asset_aliases: resolution metadata (spec §2.3) ---
    op.add_column("asset_aliases", sa.Column("source_system_type", sa.Text(), nullable=False))
    op.add_column("asset_aliases", sa.Column("vendor_path", sa.Text(), nullable=True))
    op.add_column("asset_aliases", sa.Column("vendor_metadata", postgresql.JSONB(), nullable=True))
    op.add_column("asset_aliases", sa.Column("resolution_status", sa.Text(), nullable=False,
                                             server_default="auto_resolved"))
    op.add_column("asset_aliases", sa.Column("candidate_alternatives", postgresql.JSONB(),
                                             nullable=True))
    op.add_column("asset_aliases", sa.Column("resolved_by", sa.Text(), nullable=True))
    op.add_column("asset_aliases", sa.Column("resolved_at", sa.DateTime(timezone=True),
                                             nullable=False, server_default=sa.func.now()))
    op.add_column("asset_aliases", sa.Column("validated_by", sa.Text(), nullable=True))
    op.add_column("asset_aliases", sa.Column("validated_at", sa.DateTime(timezone=True),
                                             nullable=True))


def downgrade() -> None:
    op.drop_column("asset_aliases", "validated_at")
    op.drop_column("asset_aliases", "validated_by")
    op.drop_column("asset_aliases", "resolved_at")
    op.drop_column("asset_aliases", "resolved_by")
    op.drop_column("asset_aliases", "candidate_alternatives")
    op.drop_column("asset_aliases", "resolution_status")
    op.drop_column("asset_aliases", "vendor_metadata")
    op.drop_column("asset_aliases", "vendor_path")
    op.drop_column("asset_aliases", "source_system_type")

    op.add_column("assets", sa.Column("parent_asset_id", postgresql.UUID(as_uuid=True),
                                      sa.ForeignKey("assets.asset_id"), nullable=True))
    op.create_index("ix_assets_tenant_parent", "assets", ["tenant_id", "parent_asset_id"])

    op.drop_column("assets", "updated_at")
    op.drop_column("assets", "created_at")
    op.drop_column("assets", "attributes")
    op.drop_column("assets", "status")
    op.drop_column("assets", "plant_id")
    op.drop_constraint("uq_assets_canonical_id", "assets", type_="unique")
    op.drop_column("assets", "canonical_id")
