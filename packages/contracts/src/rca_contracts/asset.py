"""AssetDescriptor + asset-resolution I/O (canonical; owned by MAR, consumed by agents).

Dual-key identity (Phase 1 spec §2.1): every asset carries both an opaque UUID PK
(`asset_id`) and a human-readable `canonical_id` of the form
`asset:{plant}:{unit}:{name}` (e.g. `asset:refinery-gc:unit-101:p-101a`).
Hierarchy is NOT modelled here — it moves to the knowledge graph in Sprint 2.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field

from ._base import StrictModel
from ._ids import AssetID, TenantID

Criticality = Literal["A", "B", "C", "D"]
ResolveStatus = Literal["resolved", "ambiguous", "unresolved"]


class AssetDescriptor(StrictModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", protected_namespaces=())

    asset_id: AssetID
    canonical_id: str
    tenant_id: TenantID
    plant_id: str
    iso14224_class: str
    iso14224_class_kg: str | None = None
    iso14224_level: int
    tag: str
    service: str | None
    criticality: Criticality
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    commissioned_at: AwareDatetime | None
    decommissioned_at: AwareDatetime | None
    location_description: str | None
    description: str | None


class ResolveAssetOutput(StrictModel):
    status: ResolveStatus
    asset: AssetDescriptor | None
    canonical_id: str | None
    confidence: float
    mapping_source: str
    alternatives: list[AssetDescriptor] = Field(default_factory=list)
