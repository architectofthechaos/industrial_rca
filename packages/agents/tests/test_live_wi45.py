"""Live end-to-end proof: document-embedding activation pipeline (Sprint 6 WI4.5 / D16 / G29).

Builds the embedding pipeline over the LIVE document MCP (HTTP host + fastmcp Client) +
``VoyageEmbeddingTransport`` + a ``PostgresRepository``, runs ``embed_for_connection`` for the
active ``document`` connection, then asserts ``search_document_embeddings`` returns rows.

Stack-gated: needs ``task probe:host`` (dynamic router + SharePoint sim) + Postgres MAR with the
pgvector ``document_embeddings`` table (migration 0007) + VOYAGE_API_KEY. SKIPs cleanly when
RCA_STACK is unset. Host/client setup mirrors test_live_wi1.py / test_dynamic_routing.py.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RCA_STACK") != "1",
    reason="requires the live HTTP host + SharePoint sim + MAR pgvector + VOYAGE_API_KEY",
)

PLANT_ID = "refinery-gc"
HOST_URL = os.environ.get("MCP_HOST_URL", "http://127.0.0.1:8100/mcp")


@pytest.mark.asyncio
async def test_activation_pipeline_embeds_and_is_searchable():
    from fastmcp import Client
    from rca_llm.embedding_config import embedding_model
    from rca_llm.transports import VoyageEmbeddingTransport
    from rca_mar.config import make_engine, make_session_factory
    from rca_mar.repository_pg import PostgresRepository

    from rca_agents.doc_source import McpDocSource
    from rca_agents.embedding_pipeline import DocumentEmbeddingPipeline

    repo = PostgresRepository(make_session_factory(make_engine()))

    # Derive the active document connection id from the live registry (same as the seed).
    conns = await repo.list_connections(plant_id=PLANT_ID, category="document", status="active")
    assert conns, "no active document connection in the live registry to embed"
    connection_id = conns[0].connection_id

    embed = VoyageEmbeddingTransport()
    model = embedding_model()

    async def _summarize(text: str) -> str:
        return text[:120]  # deterministic stub; the live LLM summary is exercised in CC5

    async with Client(HOST_URL) as client:
        pipeline = DocumentEmbeddingPipeline(
            doc_source=McpDocSource(client), embed=embed, summarize=_summarize,
            store=repo, model=model)
        count = await pipeline.embed_for_connection(connection_id, plant_id=PLANT_ID)

    assert count > 0, f"expected to embed at least one document for {connection_id}"

    # Re-embed the query text through the same transport, then search the freshly written rows.
    query_vec = (await embed.embed(model=model, texts=["pump seal failure"]))[0]
    hits = await repo.search_document_embeddings(
        connection_id=connection_id, query_embedding=query_vec, top=5)
    assert hits, f"search returned no rows for connection {connection_id} after embedding"
    assert all("score" in h for h in hits)
