"""S2.2 — PI series synthesis with mode semantics.

All three modes draw from the same per-second series (the scenario expander) but
shape it differently, matching PI Web API behaviour:

- ``recorded`` (stored): keep only points that crossed the compression deviation
  since the last stored point (the first point is always kept).
- ``interpolated``: values on a regular interval grid, each flagged interpolated.
- ``aggregated``: true aggregates (Average/Minimum/Maximum) per interval.

Units note (MVP): the simulator emits the synthesized magnitude (canonical-unit
scale from the fixture baseline) and labels it with the source's raw unit string.
True raw-unit conversion is the connector's job, so it is intentionally skipped
here. See memory: simulator-scenario-realism-gap for the related trend-only note.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import expand_series, value_at
from ..realism.inject import RealismInjector


@dataclass(frozen=True)
class PiPoint:
    timestamp: datetime
    value: float
    good: bool = True
    is_interpolated: bool = False


def _series(rp, scenario_id, signal_key, start, end, step_seconds, seed):
    return expand_series(rp, scenario_id, signal_key, start, end,
                         step_seconds=step_seconds, seed=seed)


def recorded(
    rp: RefPlant,
    scenario_id: str,
    signal_key: str,
    start: datetime,
    end: datetime,
    *,
    compression: float | None = None,
    seed: int = 0,
    realism: RealismInjector | None = None,
) -> list[PiPoint]:
    sig = rp.signals[signal_key]
    comp = compression if compression is not None else (
        sig.sampling.stored_compression_deviation or 0.0
    )
    out: list[PiPoint] = []
    last_kept: float | None = None
    for ts, value in _series(rp, scenario_id, signal_key, start, end, 1, seed):
        if last_kept is None or abs(value - last_kept) >= comp:
            out.append(_point(ts, value, realism))
            last_kept = value
    return out


def interpolated(
    rp: RefPlant,
    scenario_id: str,
    signal_key: str,
    start: datetime,
    end: datetime,
    interval_seconds: int = 60,
    *,
    seed: int = 0,
    realism: RealismInjector | None = None,
) -> list[PiPoint]:
    out: list[PiPoint] = []
    for ts, value in _series(rp, scenario_id, signal_key, start, end,
                             interval_seconds, seed):
        out.append(_point(ts, value, realism, is_interpolated=True))
    return out


def aggregated(
    rp: RefPlant,
    scenario_id: str,
    signal_key: str,
    start: datetime,
    end: datetime,
    duration_seconds: int = 3600,
    summary_type: str = "Average",
    *,
    seed: int = 0,
) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    bucket_start = start
    delta = timedelta(seconds=duration_seconds)
    while bucket_start < end:
        bucket_end = min(bucket_start + delta, end)
        values = [v for _ts, v in _series(rp, scenario_id, signal_key,
                                          bucket_start, bucket_end, 1, seed)]
        if values:
            out.append((bucket_start, _aggregate(values, summary_type)))
        bucket_start = bucket_end
    return out


def _aggregate(values: list[float], summary_type: str) -> float:
    if summary_type == "Minimum":
        return min(values)
    if summary_type == "Maximum":
        return max(values)
    if summary_type == "Total":
        return sum(values)
    return sum(values) / len(values)   # Average (default)


def _point(ts, value, realism, *, is_interpolated=False) -> PiPoint:
    good = True
    if realism is not None:
        ts = realism.skew_timestamp(ts)
        if realism.maybe_bad_quality():
            good = False
    return PiPoint(timestamp=ts, value=value, good=good, is_interpolated=is_interpolated)


def current_value(rp, scenario_id, signal_key, t, *, seed=0) -> float:
    return value_at(rp, scenario_id, signal_key, t, seed=seed)


__all__ = ["PiPoint", "recorded", "interpolated", "aggregated", "current_value"]
