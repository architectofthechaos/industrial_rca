"""PostgresRepository document-embedding cache against a REAL Postgres (Sprint 6 WI4).

Gated and run exactly like test_pg_repo.py: skips when the server behind DATABASE_URL is
unreachable. The mar conftest redirects DATABASE_URL at the throwaway test_rca_mar (migrated to
head, incl. migration 0007's `embedding vector(1024)` column + cosine IVFFlat index), so these
never touch the live rca_mar store. Vectors are 1024-dim to match the column width.

Run with: `task mar:db`.
"""
import socket
from urllib.parse import urlparse

import pytest

from rca_mar.config import database_url, make_engine, make_session_factory
from rca_mar.repository_pg import PostgresRepository


def _pg_reachable() -> bool:
    try:
        u = urlparse(database_url().replace("postgresql+asyncpg", "postgresql"))
        with socket.create_connection((u.hostname or "127.0.0.1", u.port or 5432), timeout=1):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_reachable(),
                                reason="Postgres not reachable (run `task mar:db`)")


def _vec(*nonzero):
    """Build a 1024-dim vector with the given (index, value) pairs set (rest zero)."""
    v = [0.0] * 1024
    for i, val in nonzero:
        v[i] = val
    return v


async def test_upsert_search_delete_document_embeddings():
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    conn = "refinery-gc.document.sp-default"
    await repo.delete_document_embeddings_for_connection(conn)  # clean slate

    await repo.upsert_document_embedding(
        content_hash="h1", model="voyage-3", document_id="RCA-2025-014", doc_type="rca_report",
        description="seal leak prior RCA", embedding=_vec((0, 1.0)), connection_id=conn)
    await repo.upsert_document_embedding(
        content_hash="h2", model="voyage-3", document_id="P-101A-DS", doc_type="datasheet",
        description="pump datasheet", embedding=_vec((1, 1.0)), connection_id=conn)

    # The IVFFlat index is empty/untrained on a 2-row table, so this falls back to an exact
    # seqscan — results are still correct (migration 0007's comment explains this).
    hits = await repo.search_document_embeddings(
        connection_id=conn, query_embedding=_vec((0, 0.99), (1, 0.01)), top=2,
        doc_types=["rca_report", "datasheet"])
    assert hits[0]["document_id"] == "RCA-2025-014"  # closest by cosine
    assert hits[0]["score"] > hits[1]["score"]
    assert hits[0]["doc_type"] == "rca_report"
    assert hits[0]["description"] == "seal leak prior RCA"

    await repo.delete_document_embeddings_for_connection(conn)
    assert await repo.search_document_embeddings(
        connection_id=conn, query_embedding=_vec((0, 1.0)), top=2) == []
    await engine.dispose()


async def test_upsert_is_idempotent_by_content_hash_and_model():
    """Re-upserting the same (content_hash, model) updates the row in place (no duplicates)."""
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    conn = "refinery-gc.document.idem-test"
    await repo.delete_document_embeddings_for_connection(conn)

    await repo.upsert_document_embedding(
        content_hash="dup", model="voyage-3", document_id="DOC-1", doc_type="manual",
        description="v1", embedding=_vec((0, 1.0)), connection_id=conn)
    # Same key, new vector/description -> overwrite, not a second row.
    await repo.upsert_document_embedding(
        content_hash="dup", model="voyage-3", document_id="DOC-1", doc_type="manual",
        description="v2", embedding=_vec((5, 1.0)), connection_id=conn)

    hits = await repo.search_document_embeddings(
        connection_id=conn, query_embedding=_vec((5, 1.0)), top=10)
    assert len(hits) == 1
    assert hits[0]["document_id"] == "DOC-1" and hits[0]["description"] == "v2"

    await repo.delete_document_embeddings_for_connection(conn)
    await engine.dispose()


async def test_search_scopes_to_connection_id():
    """A query only returns embeddings for the requested connection_id."""
    engine = make_engine()
    repo = PostgresRepository(make_session_factory(engine))
    conn_a = "refinery-gc.document.scope-a"
    conn_b = "refinery-gc.document.scope-b"
    await repo.delete_document_embeddings_for_connection(conn_a)
    await repo.delete_document_embeddings_for_connection(conn_b)

    await repo.upsert_document_embedding(
        content_hash="sa", model="voyage-3", document_id="A-DOC", doc_type="other",
        description="conn a", embedding=_vec((0, 1.0)), connection_id=conn_a)
    await repo.upsert_document_embedding(
        content_hash="sb", model="voyage-3", document_id="B-DOC", doc_type="other",
        description="conn b", embedding=_vec((0, 1.0)), connection_id=conn_b)

    hits = await repo.search_document_embeddings(
        connection_id=conn_a, query_embedding=_vec((0, 1.0)), top=10)
    assert [h["document_id"] for h in hits] == ["A-DOC"]

    await repo.delete_document_embeddings_for_connection(conn_a)
    await repo.delete_document_embeddings_for_connection(conn_b)
    await engine.dispose()
