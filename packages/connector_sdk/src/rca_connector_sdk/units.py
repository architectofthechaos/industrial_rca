"""Unit normalization to canonical SI (ADR-0002).

Minimal conversion registry for the MVP reference class. Gauge pressures convert
their *magnitude* to Pa and stay gauge — the value's `pressure_reference` is a
first-class field on the tag. The only refusal is gauge -> absolute without a
registered atmospheric reference; unknown units are also refused. The caller turns
either refusal into a unit_conversion_ambiguous ToolError.
"""
from __future__ import annotations

from collections.abc import Callable

from rca_contracts import PressureReference

from .errors import UnitConversionAmbiguous

# raw-unit symbol -> conversion to the canonical magnitude.
# Pressure/temperature convert to SI base (Pa, K); current, speed and volumetric flow are
# already in their canonical form per the simulator's template roles (A, MilliM-PER-SEC,
# L-PER-MIN), so they pass through identity — `canonical_unit_for` advertises those same
# targets, keeping the two functions consistent.
_CONVERSIONS: dict[str, Callable[[float], float]] = {
    "Pa": lambda v: v,
    "kPa": lambda v: v * 1_000.0,
    "bar": lambda v: v * 100_000.0,
    "psi": lambda v: v * 6_894.757293168,
    "K": lambda v: v,
    "degC": lambda v: v + 273.15,
    "degF": lambda v: (v - 32.0) * 5.0 / 9.0 + 273.15,
    "A": lambda v: v,
    "mm/s": lambda v: v,
    "MilliM-PER-SEC": lambda v: v,
    "L/min": lambda v: v,
    "L-PER-MIN": lambda v: v,
}

# gauge/relative pressure symbols -> SI magnitude scale (reference stays gauge)
_GAUGE: dict[str, float] = {
    "psig": 6_894.757293168,
    "barg": 100_000.0,
    "kpag": 1_000.0,
}

# raw-unit symbol (case-insensitive) -> canonical QUDT-ish target unit. Aligned with the
# simulator's template roles so onboarding can assign a tag's qudt_unit from its raw unit.
_CANONICAL_UNIT: dict[str, str] = {
    "psig": "kPa",
    "psi": "kPa",
    "bar": "kPa",
    "barg": "kPa",
    "kpa": "kPa",
    "kpag": "kPa",
    "degf": "DEG_C",
    "degc": "DEG_C",
    "a": "A",
    "mm/s": "MilliM-PER-SEC",
    "millim-per-sec": "MilliM-PER-SEC",
    "l/min": "L-PER-MIN",
    "l-per-min": "L-PER-MIN",
}


def to_si(
    value: float,
    raw_unit: str,
    qudt_unit: str | None,
    pressure_reference: PressureReference | None = None,
) -> float:
    """Convert ``value`` from ``raw_unit`` to canonical SI (target implied by ``raw_unit``)."""
    key = raw_unit.strip()
    low = key.lower()

    if low in _GAUGE:
        if pressure_reference == PressureReference.absolute:
            raise UnitConversionAmbiguous(
                f"{raw_unit!r} is gauge; converting to absolute needs a registered "
                f"atmospheric reference"
            )
        return value * _GAUGE[low]

    conv = _CONVERSIONS.get(key)
    if conv is None:
        raise UnitConversionAmbiguous(f"no SI conversion registered for unit {raw_unit!r}")
    return conv(value)


def canonical_unit_for(raw_unit: str) -> str | None:
    """Map a raw source unit to its canonical QUDT-ish target, or None if unknown."""
    return _CANONICAL_UNIT.get(raw_unit.strip().lower())


__all__ = ["to_si", "canonical_unit_for"]
