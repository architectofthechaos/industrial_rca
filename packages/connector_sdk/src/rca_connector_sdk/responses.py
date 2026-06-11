"""Success-envelope helper for hand-wired MCP servers (MAR, KG, asset_hierarchy).

One completed call -> one ToolResponse.ok: records the query onto a fresh
ProvenanceAccumulator (so the ADR-0010 "no data without provenance" hard-fail
path stays in force), builds the Provenance stamped queried_at=now(UTC) with a
new response_id, and wraps the payload. Data-type-agnostic: the caller's
``-> ToolResponse[T]`` annotation carries the concrete payload type.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from rca_contracts import ToolResponse

from .provenance import ProvenanceAccumulator


def ok_response(data: Any, *, tool: str, version: str, source: str, source_query: str,
                record_count: int, raw_tags: list[str] | None = None,
                notes: str | None = None,
                connection_id: str | None = None) -> ToolResponse[Any]:
    """Build provenance (queried_at=now, response_id=uuid4) and return ToolResponse.ok.

    ``connection_id`` records which configured connection served the data (2b: every
    entity response carries provenance.connection_id); the kg/asset_hierarchy callers
    leave it None.
    """
    prov = ProvenanceAccumulator()
    prov.record(source_query=source_query, record_count=record_count,
                raw_tags=raw_tags, notes=notes)
    provenance = prov.build(tool_name=tool, tool_version=version, source=source,
                            queried_at=datetime.now(timezone.utc), response_id=uuid4())
    if connection_id is not None:
        provenance = provenance.model_copy(update={"connection_id": connection_id})
    return ToolResponse.ok(data, provenance)


__all__ = ["ok_response"]
