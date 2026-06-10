"""Provenance accumulation + hard-fail build.

A connector's fetch() records what it queried; the orchestrator builds the final
Provenance. If record() was never called, build() raises — making "no data without
provenance" (ADR-0010) impossible to violate on the success path.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rca_contracts import Provenance


class ProvenanceMissingError(RuntimeError):
    """Raised when a tool tries to return data without having recorded provenance."""


class ProvenanceAccumulator:
    def __init__(self) -> None:
        self._recorded = False
        self._source_query: str = ""
        self._raw_tags: list[str] = []
        self._record_count: int = 0
        self._truncated: bool = False
        self._notes: str | None = None

    def record(
        self,
        *,
        source_query: str,
        record_count: int,
        raw_tags: list[str] | None = None,
        truncated: bool = False,
        notes: str | None = None,
    ) -> None:
        self._source_query = source_query
        self._record_count = record_count
        self._raw_tags = list(raw_tags or [])
        self._truncated = truncated
        self._notes = notes
        self._recorded = True

    def build(
        self,
        *,
        tool_name: str,
        tool_version: str,
        source: str,
        queried_at: datetime,
        response_id: UUID,
    ) -> Provenance:
        if not self._recorded:
            raise ProvenanceMissingError(
                f"{tool_name}: fetch() must call ctx.prov.record(...) before returning data"
            )
        return Provenance(
            tool_name=tool_name,
            tool_version=tool_version,
            source=source,
            source_query=self._source_query,
            queried_at=queried_at,
            response_id=response_id,
            record_count=self._record_count,
            truncated=self._truncated,
            raw_tags=self._raw_tags,
            notes=self._notes,
        )


__all__ = ["ProvenanceAccumulator", "ProvenanceMissingError"]
