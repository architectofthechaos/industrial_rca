"""Enumerations and value literals for the canonical contracts."""
from __future__ import annotations

from enum import Enum
from typing import Literal


class PressureReference(str, Enum):
    absolute = "absolute"
    gauge = "gauge"
    differential = "differential"
    not_applicable = "not_applicable"


class HistorianMode(str, Enum):
    stored = "stored"
    interpolated = "interpolated"
    aggregated = "aggregated"


Quality = Literal["good", "uncertain", "bad", "missing"]
