"""Measurement + MeasurementSeries — canonical time-series evidence."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, Field

from ._base import StrictModel
from .enums import HistorianMode, Quality
from .tag_descriptor import TagDescriptor
from .time_basis import TimeBasis


class Measurement(StrictModel):
    timestamp: AwareDatetime                   # UTC, tz-aware required
    value: float                               # canonical SI magnitude
    quality: Quality = "good"
    is_interpolated: bool = False


class MeasurementSeries(StrictModel):
    tag: TagDescriptor
    time_basis: TimeBasis
    mode: HistorianMode
    interpolation_method: Literal["linear", "previous", "step"] | None = None
    aggregation_method: Literal["avg", "min", "max", "stddev", "count"] | None = None
    aggregation_interval: timedelta | None = None
    values: list[Measurement] = Field(default_factory=list)
