"""pgvector for document_embeddings (D16/D17)

- CREATE EXTENSION IF NOT EXISTS vector
- document_embeddings.embedding: JSONB -> vector(1024)  (1024 = default model dim, voyage-3; D15)
- add doc_type + description + connection_id columns (D16)
- cosine ANN index (IVFFlat) on embedding (D17)

Idempotent; only touches rca_mar (Temporal auto-setup DBs are separate — Sprint 4 D3 re-verified).
The embedding column is a content-addressed CACHE: dropping its rows is safe (they re-embed on
next connection activation), so JSONB->vector is done by drop+re-add (no implicit cast exists).

Revision ID: 0007_pgvector_doc_embeddings
Revises: 0006_asset_class_kg
Create Date: 2026-06-12
"""

from alembic import op

revision = "0007_pgvector_doc_embeddings"
down_revision = "0006_asset_class_kg"
branch_labels = None
depends_on = None

EMBED_DIM = 1024  # D15: fixed at migration time to the default model (voyage-3) dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute(f"ALTER TABLE document_embeddings ADD COLUMN embedding vector({EMBED_DIM})")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS doc_type text")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS description text")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS connection_id text")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_embeddings_cosine ON document_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_cosine")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS connection_id")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS doc_type")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE document_embeddings ADD COLUMN embedding jsonb")
