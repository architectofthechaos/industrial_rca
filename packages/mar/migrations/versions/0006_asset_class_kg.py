"""add assets.iso14224_class_kg (D1 — KG-native equipment-class id)

MAR resolves the dotted ISO class to its KG-native equipment-class id at registration
(see rca_mar.class_binding.kg_class_for) and persists it here. NULL == unmapped; the
hard-fail is the KG upsert's job at probe time, not MAR's at registration.

Revision ID: 0006_asset_class_kg
Revises: 0005_probe_tables
Create Date: 2026-06-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_asset_class_kg"
down_revision = "0005_probe_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("iso14224_class_kg", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "iso14224_class_kg")
