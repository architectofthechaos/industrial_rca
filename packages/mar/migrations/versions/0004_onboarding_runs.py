"""onboarding_runs table (Sprint 2b §2.5).

Stores the persistent run record for each Temporal OnboardingWorkflow execution.
The workflow writes a row at start (status=running) and updates it at completion.
`connection_ids` captures which connections were requested (null = all active for
the plant). `per_category_results`, `counts`, and `errors` are written at the end.

Revision ID: 0004_onboarding_runs
Revises: 0003_connections
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_onboarding_runs"
down_revision = "0003_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("plant_id", sa.Text(), nullable=False),
        # list of connection_id strings (null = all active for the plant)
        sa.Column("connection_ids", postgresql.JSONB(), nullable=True),
        # running / completed / failed / cancelled
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # dict[category -> result_summary_string]
        sa.Column("per_category_results", postgresql.JSONB(), nullable=True),
        # {assets_new, assets_updated, assets_decommissioned,
        #  bindings_pending_review, hierarchy_nodes_upserted}
        sa.Column("counts", postgresql.JSONB(), nullable=True),
        # list of structured error dicts
        sa.Column("errors", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_onboarding_runs_plant_id", "onboarding_runs", ["plant_id"])
    op.create_index(
        "ix_onboarding_runs_plant_status",
        "onboarding_runs",
        ["plant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_runs_plant_status", table_name="onboarding_runs")
    op.drop_index("ix_onboarding_runs_plant_id", table_name="onboarding_runs")
    op.drop_table("onboarding_runs")
