"""initial MAR tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_asset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assets.asset_id"), nullable=True),
        sa.Column("iso14224_class", sa.String(), nullable=False),
        sa.Column("iso14224_level", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(), nullable=False),
        sa.Column("service", sa.String(), nullable=True),
        sa.Column("criticality", sa.String(length=1), nullable=False),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("serial_number", sa.String(), nullable=True),
        sa.Column("commissioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decommissioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_description", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_assets_tenant_class", "assets", ["tenant_id", "iso14224_class"])
    op.create_index("ix_assets_tenant_parent", "assets", ["tenant_id", "parent_asset_id"])
    op.create_index("ix_assets_tenant_tag", "assets", ["tenant_id", "tag"])

    op.create_table(
        "asset_aliases",
        sa.Column("alias_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assets.asset_id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mapping_source", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_alias_lookup", "asset_aliases", ["tenant_id", "source_system", "external_id"])
    op.create_index("ix_alias_asset", "asset_aliases", ["asset_id"])
    op.create_index(
        "uq_alias_active", "asset_aliases", ["tenant_id", "source_system", "external_id"],
        unique=True, postgresql_where=sa.text("valid_to IS NULL"))

    op.create_table(
        "asset_aliases_unresolved",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_system", sa.String(), primary_key=True),
        sa.Column("external_id", sa.String(), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("occurrence_count", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_payload", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("asset_aliases_unresolved")
    op.drop_table("asset_aliases")
    op.drop_table("assets")
