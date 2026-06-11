"""Helper for series tools: turn raw points into a normalized MeasurementSeries.

Series connectors call this from translate(). It applies unit + time normalization
(the shape-specific part) and assembles the canonical MeasurementSeries + TimeBasis.
Non-series tools (work orders, notifications, alarms, documents) build their own
response model directly; provenance/validation/envelope are still enforced by the
orchestrator regardless.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rca_contracts import HistorianMode, Measurement, MeasurementSeries

from .context import RawPoint, ToolContext
from .timeutil import build_time_basis, to_utc
from .units import to_si


def build_measurement_series(
    ctx: ToolContext,
    points: list[RawPoint],
    *,
    mode: HistorianMode,
    interpolation_method: str | None = None,
    aggregation_method: str | None = None,
    aggregation_interval=None,
) -> MeasurementSeries:
    tag = ctx.tag
    assert tag is not None, "build_measurement_series requires a tag-scoped tool"
    assert ctx.source is not None, "build_measurement_series requires a resolved source binding"
    measurements = [
        Measurement(
            timestamp=to_utc(p.timestamp, ctx.config.source_timezone),
            value=to_si(p.value, ctx.source.raw_unit, tag.qudt_unit, tag.pressure_reference),
            quality=p.quality,
            is_interpolated=p.is_interpolated,
        )
        for p in points
    ]
    if mode is HistorianMode.interpolated and interpolation_method is None:
        interpolation_method = "linear"
    return MeasurementSeries(
        tag=tag,
        time_basis=build_time_basis(
            source_clock=ctx.source_name,
            source_timezone=ctx.config.source_timezone,
            measured_at=datetime.now(timezone.utc),
        ),
        mode=mode,
        interpolation_method=interpolation_method,  # type: ignore[arg-type]
        aggregation_method=aggregation_method,      # type: ignore[arg-type]
        aggregation_interval=aggregation_interval,
        values=measurements,
    )


__all__ = ["build_measurement_series"]
