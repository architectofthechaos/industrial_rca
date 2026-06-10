"""Canonical identifier types — AssetID/TenantID (MAR); SignalID reserved (Sprint 3)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

# DEPRECATED: removed in Sprint 3 — Phase 1 has no signal registry
SignalID = Annotated[UUID, Field(description="Canonical sensor UUID from TRS")]
AssetID = Annotated[UUID, Field(description="Canonical asset UUID from MAR")]
TenantID = Annotated[UUID, Field(description="Tenant scope UUID")]
