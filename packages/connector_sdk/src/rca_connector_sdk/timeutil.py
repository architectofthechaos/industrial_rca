"""Time normalization to UTC + TimeBasis assembly (ADR-0006)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from rca_contracts import TimeBasis


def to_utc(dt: datetime, source_timezone: str) -> datetime:
    """Return ``dt`` as a UTC-aware datetime.

    Naive datetimes are interpreted in ``source_timezone`` (a source emitting
    local-time-without-tz, e.g. Maximo); aware datetimes are converted to UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(source_timezone))
    return dt.astimezone(timezone.utc)


def build_time_basis(
    *,
    source_clock: str,
    source_timezone: str,
    measured_at: datetime,
    observed_offset_seconds: float = 0.0,
    confidence: str = "configured",
) -> TimeBasis:
    return TimeBasis(
        source_clock=source_clock,
        observed_offset_seconds=observed_offset_seconds,
        offset_measurement_time=measured_at,
        source_timezone=source_timezone,
        confidence=confidence,  # type: ignore[arg-type]
    )


__all__ = ["to_utc", "build_time_basis"]
