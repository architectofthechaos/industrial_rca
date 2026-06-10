"""ResolveTagOutput — TRS resolve I/O (canonical; mirrors ResolveAssetOutput)."""
from __future__ import annotations

from pydantic import Field

from ._base import StrictModel
from .asset import ResolveStatus
from .signal import SignalDescriptor


class ResolveTagOutput(StrictModel):
    status: ResolveStatus
    signal: SignalDescriptor | None
    confidence: float
    mapping_source: str
    alternatives: list[SignalDescriptor] = Field(default_factory=list)
