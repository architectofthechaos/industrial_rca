"""Probe-run lifecycle contracts (Sprint 3 WI2/WI3) — G10/G11/G17/G18."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from ._base import StrictModel


class ProbeRunStatus(str, Enum):
    """The full probe-run status set, enumerated in one place (G18)."""

    RUNNING = "running"
    PLANNING = "planning"
    PLANNING_ABORTED = "planning_aborted"      # terminal — 3rd plan rejection
    GATHERING = "gathering"
    ANALYZING = "analyzing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"                     # terminal — approved + close phase ran
    CONCLUSION_REJECTED = "conclusion_rejected"  # terminal — engineer rejected the conclusion
    BUDGET_EXCEEDED = "budget_exceeded"         # terminal — TokenBudgetExceeded ended the probe
    FAILED = "failed"                           # terminal — unhandled activity error

    @property
    def is_terminal(self) -> bool:
        return self in {
            ProbeRunStatus.PLANNING_ABORTED,
            ProbeRunStatus.COMPLETED,
            ProbeRunStatus.CONCLUSION_REJECTED,
            ProbeRunStatus.BUDGET_EXCEEDED,
            ProbeRunStatus.FAILED,
        }


class StartProbeRequest(StrictModel):
    """`POST /probes/run` body (G10/G11)."""

    prompt: str
    plant_id: str | None = None          # omitted -> inferred in planning; defaults to single refplant
    reference_time: datetime | None = None  # omitted -> frozen to workflow start (workflow.now())
    requested_by: str                    # engineer user id (email)
