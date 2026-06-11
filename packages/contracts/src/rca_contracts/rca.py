"""RCA conclusion contracts (Sprint 3 WI5).

`EvidencePackage` -> `RcaConclusion` is the long-term engine boundary. Fishbone +
5 Whys + ranked hypotheses, every coded field validated against the KG ontology.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ._base import StrictModel
from .evidence import EvidenceCitation

AnswerSource = Literal["evidence_package", "kg", "engineer_hitl", "agent_inference"]
ActionPriority = Literal["immediate", "next_shutdown", "monitor"]
ApprovalStatus = Literal["approved", "approved_with_edits", "rejected"]


class FiveWhysStep(StrictModel):
    rank: int                            # 1, 2, 3, ...
    why_question: str
    answer: str
    answer_source: AnswerSource
    supporting_evidence: list[EvidenceCitation] = Field(default_factory=list)


class FiveWhysChain(StrictModel):
    chain_id: UUID
    initial_problem: str
    steps: list[FiveWhysStep] = Field(default_factory=list)
    terminal_root_cause: str
    confidence: float


class FishboneCause(StrictModel):
    cause: str
    sub_causes: list[str] = Field(default_factory=list)
    supporting_evidence: list[EvidenceCitation] = Field(default_factory=list)


class FishboneCategory(StrictModel):
    category: Literal[
        "Manpower", "Method", "Machine", "Material", "Measurement", "Environment"
    ]
    causes: list[FishboneCause] = Field(default_factory=list)


class RankedHypothesis(StrictModel):
    rank: int
    iso14224_failure_mode: str           # KG-validated (FailureMode.code)
    iso14224_mechanism: str              # KG-validated (FailureMechanism.id)
    iso14224_cause: str | None = None
    confidence: float
    narrative: str
    supporting_evidence: list[EvidenceCitation] = Field(default_factory=list)
    contradicting_evidence: list[EvidenceCitation] = Field(default_factory=list)


class RecommendedAction(StrictModel):
    action: str
    rationale: str
    priority: ActionPriority
    estimated_effort: str | None = None
    target: str | None = None                  # G7 — e.g. "mechanical_seal", "NDE_bearing"
    preconditions: list[str] = Field(default_factory=list)  # G7


class OpenDataRequest(StrictModel):           # G8 — distinct from recommended_actions
    request: str
    rationale: str
    target: str | None = None


class EngineerEdit(StrictModel):
    field_path: str
    before: Any = None
    after: Any = None
    edited_at: datetime
    engineer_notes: str | None = None


class RcaConclusion(StrictModel):
    conclusion_id: UUID
    probe_run_id: UUID
    evidence_package_id: UUID
    canonical_id: str
    primary_hypothesis: RankedHypothesis
    alternative_hypotheses: list[RankedHypothesis] = Field(default_factory=list)
    fishbone: list[FishboneCategory] = Field(default_factory=list)
    five_whys: FiveWhysChain
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    open_data_requests: list[OpenDataRequest] = Field(default_factory=list)   # G8
    engineer_edits: list[EngineerEdit] = Field(default_factory=list)
    engineer_approval_status: ApprovalStatus | None = None
    engineer_notes: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    agent_name: str = "rca_agent_v1"
    agent_version: str
    generated_at: datetime
    finalized_at: datetime | None = None
    schema_version: str = "v1"
