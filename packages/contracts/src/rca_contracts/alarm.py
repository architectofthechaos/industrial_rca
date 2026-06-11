"""Alarm — a canonical alarm / event-frame record (SPEC-001)."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from ._base import StrictModel
from ._ids import AssetID


class Alarm(StrictModel):
    asset_id: AssetID
    tag_name: str | None = None
    timestamp: AwareDatetime
    priority: int
    state: Literal["activated", "acknowledged", "cleared", "shelved"]
    message: str
    source_system: str
