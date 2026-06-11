"""TagDescriptor — the entity-vocabulary identity the agent reasons over.

A tag is a vendor's named time-series handle bound to a canonical asset. Unlike the old
signal descriptor (which assumed a TRS-issued signal UUID), a TagDescriptor is keyed by the
asset's canonical_id plus the source's raw tag string; canonicalization is the onboarding
pipeline's job, not a precondition for the contract.
"""
from __future__ import annotations

from pydantic import field_validator

from ._base import StrictModel
from .canonical import parse_canonical_id
from .enums import PressureReference


class TagDescriptor(StrictModel):
    canonical_id: str                          # asset:{plant}:{unit}:{name}
    tag_name: str                              # vendor's tag string, e.g. "P-101A.discharge_pressure"
    role: str | None = None                    # e.g. "discharge_pressure"
    source_unit: str | None = None             # raw unit the source emits
    qudt_unit: str | None = None               # canonical QUDT unit/URI
    pressure_reference: PressureReference = PressureReference.not_applicable
    description: str | None = None

    @field_validator("canonical_id")
    @classmethod
    def _canonical_id_is_well_formed(cls, value: str) -> str:
        parse_canonical_id(value)   # raises ValueError on a malformed canonical_id
        return value
