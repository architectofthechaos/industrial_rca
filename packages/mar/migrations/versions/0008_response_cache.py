"""response_cache for cross-process LLM determinism replay (Sprint 6 WI5)

A content-addressed cache keyed by ``prompt_hash`` (SHA-256 of the rendered prompt). The
``InMemoryResponseCache`` only replays within a single process; this table lets determinism
replay work ACROSS processes (e.g. a record run and a later replay run, or separate Temporal
activities). The payload is the LLM client's cached value dict
(``{content, structured, model, model_version, input_tokens, output_tokens}``).

Idempotent; only touches rca_mar (Temporal auto-setup DBs are separate — Sprint 4 D3).

Revision ID: 0008_response_cache
Revises: 0007_pgvector_doc_embeddings
Create Date: 2026-06-12
"""

from alembic import op

revision = "0008_response_cache"
down_revision = "0007_pgvector_doc_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS response_cache ("
        "prompt_hash text PRIMARY KEY, "
        "payload jsonb NOT NULL, "
        "created_at timestamptz NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.drop_table("response_cache")
