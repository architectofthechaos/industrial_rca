"""Investigation-plan contracts (Sprint 3 WI3)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import StrictModel

PlanStepType = Literal["tag_history", "work_orders", "documents", "operator_logs", "kg_query"]


class FailureModeCandidate(StrictModel):
    iso14224_code: str                   # ontology FailureMode.code, e.g. "ELP"
    name: str
    rank: int
    confidence: float
    reasoning: str


class PlanStep(StrictModel):
    step_id: UUID
    step_type: PlanStepType
    description: str                     # engineer-readable
    parameters: dict = Field(default_factory=dict)   # step-type-specific
    rationale: str
    estimated_cost: str | None = None    # "fast" | "slow" | "expensive"


class InvestigationPlan(StrictModel):
    plan_id: UUID
    probe_run_id: UUID
    version: int                         # incremented on each edit cycle
    asset_canonical_id: str
    candidate_failure_modes: list[FailureModeCandidate] = Field(default_factory=list)  # ranked
    steps: list[PlanStep] = Field(default_factory=list)
    engineer_notes: str | None = None
    finalized_at: datetime | None = None
