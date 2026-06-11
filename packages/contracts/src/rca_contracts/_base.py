"""Shared base model: Pydantic v2 strict, frozen, extra-forbid (ADR-0007)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class JsonModel(BaseModel):
    """Frozen + extra-forbid, but NOT strict: these contracts round-trip through JSON-mode
    dicts (Temporal ``graph_state``, Postgres JSONB), so they must coerce string UUIDs /
    ISO datetimes back on ``model_validate``. Used by the Sprint-3 probe/agent contracts."""

    model_config = ConfigDict(strict=False, frozen=True, extra="forbid")
