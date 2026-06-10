"""SignalDescriptor — the canonical sensor identity the agent reasons over."""
from __future__ import annotations

from ._base import StrictModel
from ._ids import AssetID, SignalID, TenantID
from .enums import PressureReference


class SignalDescriptor(StrictModel):
    signal_id: SignalID
    tenant_id: TenantID
    asset_id: AssetID
    role: str                                  # e.g. "discharge_pressure"
    qudt_unit: str                             # QUDT URI for the canonical unit
    pressure_reference: PressureReference = PressureReference.not_applicable
    range_min: float | None = None
    range_max: float | None = None
    description: str | None = None
