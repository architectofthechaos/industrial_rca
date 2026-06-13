"""Document-embedding activation listener (Sprint 6 WI4 / D16 / G29).

Wires document embedding to fire on a ``document``-connection activation. The connections_api
activation seam calls ``ActivationListener(row)`` failure-safely after a successful
``/activate``; this module builds that listener so that, for ``category=="document"``
connections, the ``DocumentEmbeddingPipeline`` runs over the connected source.

Three pieces:
- ``make_document_embedding_listener(pipeline)``  — the document-only gate + pipeline trigger;
- ``llm_summarizer(llm)``                          — adapts an ``LLMClient`` to the pipeline's
                                                     ``summarize`` callable (summarize_document/v1);
- ``build_document_embedding_listener(...)``       — the live composition: assembles McpDocSource
                                                     + embed transport + llm summarizer + MAR repo
                                                     store into a pipeline and returns the listener.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from rca_connections_api import ActivationListener
from rca_llm.embedding_config import embedding_model

from .doc_source import McpDocSource
from .embedding_pipeline import DocumentEmbeddingPipeline

logger = logging.getLogger(__name__)


def make_document_embedding_listener(pipeline: Any) -> ActivationListener:
    """Return an ActivationListener that embeds documents for a ``document`` connection.

    Non-document categories are a no-op. The connections_api seam already swallows listener
    exceptions (an embed failure must not fail activation), so this does not double-guard.
    """
    async def _listener(row: Any) -> None:
        if getattr(row, "category", None) != "document":
            return
        await pipeline.embed_for_connection(row.connection_id, plant_id=row.plant_id)

    return _listener


def llm_summarizer(llm: Any) -> Callable[[str], Awaitable[str]]:
    """Adapt an LLMClient to the pipeline's ``summarize: (str) -> Awaitable[str]`` callable.

    Calls the ``summarize_document/v1`` prompt with the document text and returns the summary.
    The prompt is plain-text (no output_schema) so ``.content`` is canonical; a ``.structured``
    fallback keeps it working if the prompt is later given a schema. Tolerant: returns "" on a
    blank result rather than raising (the pipeline embeds without a description on failure).
    """
    async def _summarize(text: str) -> str:
        resp = await llm.complete(
            "summarize_document", "v1", {"document_text": text},
            correlation_id=f"embed-summary:{uuid4()}")
        content = (getattr(resp, "content", None) or "").strip()
        if content:
            return content
        structured = getattr(resp, "structured", None) or {}
        return str(structured.get("summary", "")).strip()

    return _summarize


def make_document_embedding_invalidator(store: Any) -> ActivationListener:
    """Return an ActivationListener that DELETES a document connection's embeddings on disconnect.

    Non-document categories are a no-op. ``store`` is the MAR repo (has
    delete_document_embeddings_for_connection).
    """
    async def _listener(row: Any) -> None:
        if getattr(row, "category", None) != "document":
            return
        await store.delete_document_embeddings_for_connection(row.connection_id)

    return _listener


def build_document_embedding_listener(
    *, doc_client: Any, llm: Any, repo: Any,
    embed_transport: Any = None, model: str | None = None,
) -> ActivationListener:
    """Assemble the pipeline and return the activation listener (live connections_api wiring).

    ``embed_transport`` MUST be supplied by the caller — live passes ``VoyageEmbeddingTransport``,
    tests pass ``HashEmbeddingTransport``. It is intentionally NOT defaulted to ``llm.embed`` here:
    the pipeline needs the raw ``EmbeddingTransport`` (``embed(model=, texts=)`` -> vectors), which
    is a different shape from ``LLMClient.embed``, and defaulting silently would hide a wiring gap.
    """
    if embed_transport is None:
        raise ValueError(
            "embed_transport is required (e.g. VoyageEmbeddingTransport live / "
            "HashEmbeddingTransport in tests); it is not defaulted to keep the wiring explicit")
    pipeline = DocumentEmbeddingPipeline(
        doc_source=McpDocSource(doc_client),
        embed=embed_transport,
        summarize=llm_summarizer(llm),
        store=repo,
        model=model or embedding_model())
    return make_document_embedding_listener(pipeline)


__all__ = [
    "make_document_embedding_listener",
    "make_document_embedding_invalidator",
    "llm_summarizer",
    "build_document_embedding_listener",
]
