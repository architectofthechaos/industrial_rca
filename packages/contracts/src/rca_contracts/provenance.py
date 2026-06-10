"""Provenance — attached to every tool result; no tool returns data without it (ADR-0010)."""
from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field

from ._base import StrictModel


class Provenance(StrictModel):
    tool_name: str
    tool_version: str
    source: str                                # e.g. "echo", "pi_historian_main"
    source_query: str                          # the actual query/URL, sanitized
    queried_at: AwareDatetime                  # UTC
    response_id: UUID                          # unique per invocation; audit FK
    record_count: int
    truncated: bool
    raw_tags: list[str] = Field(default_factory=list)   # forensic only — never in LLM context
    notes: str | None = None
