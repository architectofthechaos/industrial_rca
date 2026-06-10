"""Unit normalization to canonical SI (ADR-0002).

Minimal conversion registry for the MVP reference class. Gauge pressures convert
their *magnitude* to Pa and stay gauge — the value's `pressure_reference` is a
first-class field on the signal. The only refusal is gauge -> absolute without a
registered atmospheric reference; unknown units are also refused. The caller turns
either refusal into a unit_conversion_ambiguous ToolError.
"""
from __future__ import annotations

from collections.abc import Callable

from rca_contracts import PressureReference

from .errors import UnitConversionAmbiguous

# raw-unit symbol -> conversion to SI (Pa, K, A, ...)
_CONVERSIONS: dict[str, Callable[[float], float]] = {
    "Pa": lambda v: v,
    "kPa": lambda v: v * 1_000.0,
    "bar": lambda v: v * 100_000.0,
    "psi": lambda v: v * 6_894.757293168,
    "K": lambda v: v,
    "degC": lambda v: v + 273.15,
    "A": lambda v: v,
}

# gauge/relative pressure symbols -> SI magnitude scale (reference stays gauge)
_GAUGE: dict[str, float] = {
    "psig": 6_894.757293168,
    "barg": 100_000.0,
    "kpag": 1_000.0,
}


def to_si(
    value: float,
    raw_unit: str,
    qudt_unit: str,
    pressure_reference: PressureReference | None = None,
) -> float:
    """Convert ``value`` from ``raw_unit`` to canonical SI (target implied by ``qudt_unit``)."""
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


__all__ = ["to_si"]
