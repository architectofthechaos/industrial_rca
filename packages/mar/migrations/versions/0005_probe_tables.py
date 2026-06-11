"""Sprint 3 probe data layer: probe_runs, probe_memory, probe_graph_state,
evidence_packages, rca_conclusions, llm_calls, document_embeddings.

Mirrors the onboarding_runs pattern (Temporal-run record + JSONB result columns) for the
probe lifecycle (G16/G17/G18). The embedding column is JSONB (portable); provisioning the
pgvector extension + a native ``vector`` column is a documented follow-up (needs a
pgvector-enabled Postgres image), as is the pg_cron 1-month retention job (§2.7/§2.8).

Revision ID: 0005_probe_tables
Revises: 0004_onboarding_runs
Create Date: 2026-06-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_probe_tables"
down_revision = "0004_onboarding_runs"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "probe_runs",
        sa.Column("probe_run_id", _UUID, primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("plant_id", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("reference_time", _TS, nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("final_canonical_id", sa.Text(), nullable=True),
        sa.Column("token_usage", _JSONB, nullable=True),
        sa.Column("followup_wo", _JSONB, nullable=True),
        sa.Column("errors", _JSONB, nullable=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("completed_at", _TS, nullable=True),
    )
    op.create_index("ix_probe_runs_plant_id", "probe_runs", ["plant_id"])
    op.create_index("ix_probe_runs_plant_status", "probe_runs", ["plant_id", "status"])

    op.create_table(
        "probe_memory",
        sa.Column("probe_run_id", _UUID, sa.ForeignKey("probe_runs.probe_run_id"),
                  primary_key=True),
        sa.Column("conversation", _JSONB, nullable=True),
        sa.Column("current_plan", _JSONB, nullable=True),
        sa.Column("plan_history", _JSONB, nullable=True),
        sa.Column("working_knowledge", _JSONB, nullable=True),
        sa.Column("agent_scratchpad", _JSONB, nullable=True),
        sa.Column("token_usage", _JSONB, nullable=True),
        sa.Column("last_updated_at", _TS, nullable=False),
        sa.Column("archived_at", _TS, nullable=True),
    )

    op.create_table(
        "probe_graph_state",
        sa.Column("probe_run_id", _UUID, sa.ForeignKey("probe_runs.probe_run_id"),
                  primary_key=True),
        sa.Column("ref", sa.Text(), primary_key=True),
        sa.Column("state", _JSONB, nullable=False),
        sa.Column("created_at", _TS, nullable=False),
    )

    op.create_table(
        "evidence_packages",
        sa.Column("evidence_package_id", _UUID, primary_key=True),
        sa.Column("probe_run_id", _UUID, sa.ForeignKey("probe_runs.probe_run_id"),
                  nullable=False),
        sa.Column("canonical_id", sa.Text(), nullable=False),
        sa.Column("investigated_failure_modes", _JSONB, nullable=True),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="v1"),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("assembled_at", _TS, nullable=False),
    )
    op.create_index("ix_evidence_packages_probe", "evidence_packages", ["probe_run_id"])
    op.create_index("ix_evidence_packages_canonical", "evidence_packages", ["canonical_id"])

    op.create_table(
        "rca_conclusions",
        sa.Column("conclusion_id", _UUID, primary_key=True),
        sa.Column("probe_run_id", _UUID, sa.ForeignKey("probe_runs.probe_run_id"),
                  nullable=False),
        sa.Column("evidence_package_id", _UUID, nullable=False),
        sa.Column("canonical_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=True),
        sa.Column("agent_version", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Text(), nullable=False, server_default="v1"),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("llm_call_ids", _JSONB, nullable=True),
        sa.Column("generated_at", _TS, nullable=False),
        sa.Column("finalized_at", _TS, nullable=True),
    )
    op.create_index("ix_rca_conclusions_canonical", "rca_conclusions", ["canonical_id"])

    op.create_table(
        "llm_calls",
        sa.Column("llm_call_id", _UUID, primary_key=True),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("probe_run_id", _UUID, nullable=True),
        sa.Column("prompt_name", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("request_payload", _JSONB, nullable=True),
        sa.Column("response_payload", _JSONB, nullable=True),
        sa.Column("created_at", _TS, nullable=False),
    )
    op.create_index("ix_llm_calls_correlation", "llm_calls", ["correlation_id"])
    op.create_index("ix_llm_calls_probe", "llm_calls", ["probe_run_id"])

    op.create_table(
        "document_embeddings",
        sa.Column("content_hash", sa.Text(), primary_key=True),
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("embedding", _JSONB, nullable=True),   # follow-up: pgvector `vector` column
        sa.Column("created_at", _TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("document_embeddings")
    op.drop_index("ix_llm_calls_probe", table_name="llm_calls")
    op.drop_index("ix_llm_calls_correlation", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_rca_conclusions_canonical", table_name="rca_conclusions")
    op.drop_table("rca_conclusions")
    op.drop_index("ix_evidence_packages_canonical", table_name="evidence_packages")
    op.drop_index("ix_evidence_packages_probe", table_name="evidence_packages")
    op.drop_table("evidence_packages")
    op.drop_table("probe_graph_state")
    op.drop_table("probe_memory")
    op.drop_index("ix_probe_runs_plant_status", table_name="probe_runs")
    op.drop_index("ix_probe_runs_plant_id", table_name="probe_runs")
    op.drop_table("probe_runs")
