"""Hermetic tests for the document-embedding activation listener (Sprint 6 WI4 / D16 / G29).

Verifies:
- make_document_embedding_listener fires pipeline.embed_for_connection(connection_id,
  plant_id=...) for a category=="document" ConnectionRow;
- it does NOT fire for any other category;
- llm_summarizer adapts an LLMClient.complete result to the pipeline's summarize callable;
- build_document_embedding_listener assembles a working listener (Hash transport) end-to-end.
"""
from __future__ import annotations

import pytest
from rca_llm.testing import HashEmbeddingTransport

from rca_agents.embedding_listener import (
    build_document_embedding_listener,
    llm_summarizer,
    make_document_embedding_invalidator,
    make_document_embedding_listener,
)


class _Row:
    def __init__(self, *, connection_id="conn-1", plant_id="refinery-gc", category="document",
                 status="active"):
        self.connection_id = connection_id
        self.plant_id = plant_id
        self.category = category
        self.status = status


class _FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def embed_for_connection(self, connection_id, **kwargs):
        self.calls.append((connection_id, kwargs))
        return len(self.calls)


# ------------------------------------------------------------------ listener gating


async def test_document_row_triggers_embed():
    pipe = _FakePipeline()
    listener = make_document_embedding_listener(pipe)
    await listener(_Row(connection_id="conn-doc", plant_id="refinery-gc"))
    assert pipe.calls == [("conn-doc", {"plant_id": "refinery-gc"})]


@pytest.mark.parametrize("category", ["historian", "cmms", "operator_log", "asset"])
async def test_non_document_row_does_not_trigger(category):
    pipe = _FakePipeline()
    listener = make_document_embedding_listener(pipe)
    await listener(_Row(category=category))
    assert pipe.calls == []


async def test_missing_category_does_not_trigger():
    class _Bare:
        connection_id = "c"
        plant_id = "p"

    pipe = _FakePipeline()
    listener = make_document_embedding_listener(pipe)
    await listener(_Bare())  # type: ignore[arg-type]
    assert pipe.calls == []


# ------------------------------------------------------------------ llm_summarizer


class _Resp:
    def __init__(self, *, content="", structured=None):
        self.content = content
        self.structured = structured


class _FakeLLM:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[tuple] = []

    async def complete(self, prompt_name, prompt_version, variables, **kwargs):
        self.calls.append((prompt_name, prompt_version, variables, kwargs))
        return self._resp


async def test_llm_summarizer_reads_plain_content():
    llm = _FakeLLM(_Resp(content="A short factual summary."))
    summarize = llm_summarizer(llm)
    out = await summarize("Pump datasheet body text")
    assert out == "A short factual summary."
    name, version, variables, _ = llm.calls[0]
    assert name == "summarize_document" and version == "v1"
    assert variables == {"document_text": "Pump datasheet body text"}


async def test_llm_summarizer_falls_back_to_structured_summary():
    llm = _FakeLLM(_Resp(content="", structured={"summary": "Structured summary."}))
    summarize = llm_summarizer(llm)
    assert await summarize("body") == "Structured summary."


async def test_llm_summarizer_tolerates_empty():
    llm = _FakeLLM(_Resp(content="", structured=None))
    summarize = llm_summarizer(llm)
    assert await summarize("body") == ""


# ------------------------------------------------------------------ live composition builder


class _Store:
    def __init__(self):
        self.rows: list[dict] = []

    async def upsert_document_embedding(self, **kw):
        self.rows.append(kw)

    async def delete_document_embeddings_for_connection(self, connection_id):
        pass


_PROV = {"tool_name": "x", "tool_version": "v1", "source": "sim", "connection_id": None,
         "source_query": "q", "queried_at": "2026-03-30T12:00:00+00:00",
         "response_id": "0190d3c9-0000-7000-8000-000000000abc", "record_count": 1,
         "truncated": False, "raw_tags": [], "notes": None}
_DS = {"document_id": "d1", "asset_id": None, "title": "DS", "doc_type": "datasheet",
       "uri": "/d1", "last_modified": "2026-03-30T12:00:00+00:00", "excerpt": "body"}


class _StubDocClient:
    """Minimal fastmcp-Client-shaped stub for build_document_embedding_listener wiring.

    One datasheet for list_by_type("datasheet"); empty for any other type; get returns the doc.
    """

    async def call_tool(self, tool, args):
        req = args["request"]
        if tool == "document.list_by_type":
            payload = [_DS] if req["doc_type"] == "datasheet" else []
        else:  # document.get
            payload = _DS

        class _Res:
            structured_content = {"data": payload, "provenance": _PROV, "error": None}
            data = None

        return _Res()


async def test_build_listener_end_to_end_with_hash_transport():
    store = _Store()
    llm = _FakeLLM(_Resp(content="summary"))
    listener = build_document_embedding_listener(
        doc_client=_StubDocClient(), llm=llm, repo=store,
        embed_transport=HashEmbeddingTransport(dim=1024), model="voyage-3")
    await listener(_Row(connection_id="conn-doc", plant_id="refinery-gc"))
    assert len(store.rows) == 1
    assert store.rows[0]["doc_type"] == "datasheet"
    assert len(store.rows[0]["embedding"]) == 1024


async def test_build_listener_requires_embed_transport():
    with pytest.raises(ValueError, match="embed_transport"):
        build_document_embedding_listener(
            doc_client=_StubDocClient(), llm=_FakeLLM(_Resp()), repo=_Store())


# ------------------------------------------------------------------ invalidator


class _FakeStore:
    """Records delete_document_embeddings_for_connection calls."""

    def __init__(self):
        self.deleted: list[str] = []

    async def delete_document_embeddings_for_connection(self, connection_id: str) -> None:
        self.deleted.append(connection_id)


async def test_invalidator_document_row_deletes_embeddings():
    """A document row triggers delete_document_embeddings_for_connection with correct id."""
    store = _FakeStore()
    invalidator = make_document_embedding_invalidator(store)
    await invalidator(_Row(connection_id="conn-doc", category="document"))
    assert store.deleted == ["conn-doc"]


@pytest.mark.parametrize("category", ["historian", "cmms", "operator_log", "asset"])
async def test_invalidator_non_document_row_is_noop(category):
    """Non-document categories must NOT trigger a delete call."""
    store = _FakeStore()
    invalidator = make_document_embedding_invalidator(store)
    await invalidator(_Row(category=category))
    assert store.deleted == []


async def test_invalidator_round_trip_with_in_memory_repository():
    """Embed via pipeline into InMemoryRepository, then invalidate; embeddings gone."""
    from rca_llm.testing import HashEmbeddingTransport
    from rca_mar.repository import InMemoryRepository

    repo = InMemoryRepository()

    # Embed documents into the repo using the real pipeline
    listener = build_document_embedding_listener(
        doc_client=_StubDocClient(),
        llm=_FakeLLM(_Resp(content="summary")),
        repo=repo,
        embed_transport=HashEmbeddingTransport(dim=1024),
        model="voyage-3",
    )
    await listener(_Row(connection_id="conn-doc", plant_id="refinery-gc", category="document"))

    # Verify something was embedded
    assert len(repo._doc_embeddings) == 1
    assert repo._doc_embeddings[0]["connection_id"] == "conn-doc"

    # Now invalidate using the real InMemoryRepository as the store
    invalidator = make_document_embedding_invalidator(repo)
    await invalidator(_Row(connection_id="conn-doc", category="document"))

    # Embeddings must be gone
    assert repo._doc_embeddings == []
