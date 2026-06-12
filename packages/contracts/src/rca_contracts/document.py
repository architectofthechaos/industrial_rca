"""DocumentRef — a canonical reference to a source document (SPEC-001)."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from ._base import JsonModel, StrictModel
from ._ids import AssetID

DocType = Literal["datasheet", "p_and_id", "rca_report", "soop", "manual", "other"]


class DocumentRef(StrictModel):
    document_id: str
    asset_id: AssetID | None = None
    title: str
    doc_type: DocType
    uri: str
    last_modified: AwareDatetime
    excerpt: str | None = None                 # relevant snippet / fetched content for the probe


class DocumentEmbeddingHit(JsonModel):
    """A single cosine-similarity hit from the MAR document_embedding.search tool (Sprint 6 WI4).

    `score` is `1 - cosine_distance` (≈[0, 1], higher == more similar); rows arrive ordered by
    descending score. `doc_type`/`description` mirror the cached document_embeddings columns and
    may be null for rows written before those were populated. A JsonModel (not StrictModel) so it
    round-trips through the MCP ToolResponse JSONB envelope like the other probe-era contracts."""

    document_id: str
    doc_type: str | None = None
    description: str | None = None
    score: float
