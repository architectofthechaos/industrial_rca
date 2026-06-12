"""Connect-only document embedding (D16): on a `document` connection activation, enumerate
datasheet + rca_report docs from the connected source, generate a short LLM summary (description),
embed (title + excerpt + description), and upsert into MAR's document_embeddings tagged with
connection_id + content_hash. p_and_id is excluded this sprint."""
from __future__ import annotations

import hashlib
from typing import Any, Protocol

EMBED_DOC_TYPES = ("datasheet", "rca_report")  # D16: p_and_id excluded


class DocSource(Protocol):
    async def list_by_type(self, doc_type: str, plant_id: str) -> list[dict]: ...
    async def get(self, document_id: str, plant_id: str) -> dict: ...


class EmbeddingStore(Protocol):
    async def upsert_document_embedding(self, **kwargs: Any) -> None: ...
    async def delete_document_embeddings_for_connection(self, connection_id: str) -> None: ...


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DocumentEmbeddingPipeline:
    def __init__(self, *, doc_source: DocSource, embed: Any, summarize: Any,
                 store: EmbeddingStore, model: str) -> None:
        self._docs = doc_source
        self._embed = embed
        self._summarize = summarize
        self._store = store
        self._model = model

    async def embed_for_connection(self, connection_id: str, *, plant_id: str,
                                   replace: bool = True) -> int:
        """Embed datasheet+rca_report docs for a connection. replace=True invalidates prior rows
        first (re-embed on refresh / invalidate on disconnect). Returns the count embedded."""
        if replace:
            await self._store.delete_document_embeddings_for_connection(connection_id)
        count = 0
        for doc_type in EMBED_DOC_TYPES:
            for ref in await self._docs.list_by_type(doc_type, plant_id):
                full = await self._docs.get(ref["document_id"], plant_id)
                body = f"{full.get('title', '')}\n{full.get('excerpt', '') or ''}".strip()
                description = await self._safe_summarize(body)
                text = f"{body}\n{description}".strip()
                vec = (await self._embed.embed(model=self._model, texts=[text]))[0]
                await self._store.upsert_document_embedding(
                    content_hash=_content_hash(f"{connection_id}:{ref['document_id']}:{text}"),
                    model=self._model, document_id=ref["document_id"], doc_type=doc_type,
                    description=description, embedding=vec, connection_id=connection_id)
                count += 1
        return count

    async def _safe_summarize(self, body: str) -> str:
        if not body:
            return ""
        try:
            return await self._summarize(body)
        except Exception:  # noqa: BLE001 — a summary failure must not block the embed
            return ""


__all__ = ["DocumentEmbeddingPipeline", "DocSource", "EmbeddingStore", "EMBED_DOC_TYPES"]
