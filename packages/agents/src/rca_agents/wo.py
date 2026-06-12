"""Follow-up work-order creators (Sprint 3 WI6) — the close phase's WO write seam.

``McpWorkOrderCreator`` calls the additive ``work_order.create`` MCP tool over HTTP (production);
``FakeWorkOrderCreator`` mints a deterministic wonum in-process for hermetic tests. Both key the
wonum on (probe_run_id, conclusion_id) so re-running the close phase is idempotent (§6.3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from rca_contracts import ToolResponse


def mint_wonum(references: dict) -> str:
    digest = uuid5(NAMESPACE_URL, f"rca-wo:{references.get('probe_run_id', '')}:"
                   f"{references.get('conclusion_id', '')}").hex[:10].upper()
    return f"WO-RCA-{digest}"


class FakeWorkOrderCreator:
    def __init__(self) -> None:
        self.created: dict[str, dict] = {}

    async def create(self, *, canonical_id: str, description: str, priority: str,
                     work_type: str, references: dict, requested_by: str,
                     reported_at: datetime) -> dict:
        wonum = mint_wonum(references)
        record = {"work_order_id": wonum, "canonical_id": canonical_id,
                  "description": description, "priority": priority, "work_type": work_type,
                  "status": "WAPPR", "requested_by": requested_by,
                  "reported_at": reported_at.isoformat(), "references": references}
        self.created[wonum] = record   # idempotent upsert by wonum
        return record


class McpWorkOrderCreator:
    """Calls the Maximo ``work_order.create`` MCP tool over a fastmcp.Client (G11).

    The connector mints a deterministic wonum from references.{probe_run_id, conclusion_id}, so
    Temporal activity retries are idempotent (maximo server mints from those refs).
    """

    def __init__(self, client: Any) -> None:
        self._c = client

    async def create(self, *, canonical_id: str, description: str, priority: str,
                     work_type: str, references: dict, requested_by: str,
                     reported_at: datetime) -> dict:
        res = await self._c.call_tool("work_order.create", {"request": {
            "canonical_id": canonical_id, "description": description, "priority": priority,
            "work_type": work_type, "references": references, "requested_by": requested_by,
            "reported_at": reported_at.isoformat()}})
        payload = res.structured_content
        if payload is None:
            raise RuntimeError(f"work_order.create returned no structured content: {res.data!r}")
        resp: ToolResponse[Any] = ToolResponse[Any].model_validate(payload, strict=False)
        if resp.error is not None:
            raise RuntimeError(f"work_order.create failed: {resp.error}")
        return dict(resp.data or {})


__all__ = ["FakeWorkOrderCreator", "McpWorkOrderCreator", "mint_wonum"]
