"""Shared base model: Pydantic v2 strict, frozen, extra-forbid (ADR-0007)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
