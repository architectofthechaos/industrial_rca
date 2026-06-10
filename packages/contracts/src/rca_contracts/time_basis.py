"""TimeBasis — accompanies every measurement series so reviewers can judge clock slop (ADR-0006)."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from ._base import StrictModel


class TimeBasis(StrictModel):
    source_clock: str
    observed_offset_seconds: float
    offset_measurement_time: AwareDatetime
    source_timezone: str                       # IANA tz, e.g. "America/Chicago"
    confidence: Literal["ntp_synced", "configured", "estimated", "unknown"]
