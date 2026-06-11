"""Follow-up work-order creators (Sprint 3 WI6) — the close phase's WO write seam.

``McpWorkOrderCreator`` calls the additive ``work_order.create`` MCP tool over HTTP (production);
``FakeWorkOrderCreator`` mints a deterministic wonum in-process for hermetic tests. Both key the
wonum on (probe_run_id, conclusion_id) so re-running the close phase is idempotent (§6.3)."""
from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5


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


__all__ = ["FakeWorkOrderCreator", "mint_wonum"]
