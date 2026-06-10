"""WorkOrder — canonical CMMS work order / notification (SPEC-001).

Both Maximo work orders and SAP PM notifications normalize to this shape, so
overlapping assets compare directly across sources.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from ._base import StrictModel
from ._ids import AssetID


class WorkOrder(StrictModel):
    work_order_id: str
    asset_id: AssetID
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    priority: str
    status: str
    failure_code: str | None = None            # ISO 14224 code where known
    description: str
    actions_taken: str | None = None
    source_system: Literal["maximo", "sap_pm"]
