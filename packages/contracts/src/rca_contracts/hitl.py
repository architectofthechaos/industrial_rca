"""Human-in-the-loop (HITL) contracts (Sprint 3 WI3).

A single bidirectional channel shared by planning, gather, and conclusion-review
(decision #3/#4). Questions are batched per turn; the engineer answers via one
`HitlResponse` that the FastAPI handler relays to the workflow as a Temporal signal.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ._base import JsonModel

QuestionType = Literal["clarification", "context", "scope", "approval"]


class HitlQuestion(JsonModel):
    question_id: UUID
    text: str
    question_type: QuestionType
    candidates: list[dict] | None = None   # e.g. asset shortlist when asking which pump
    required: bool = True


class HitlTurn(JsonModel):
    turn_id: UUID
    questions: list[HitlQuestion] = Field(default_factory=list)   # batched, relevant
    proposed_plan: dict | None = None        # set at the plan-approval gate
    proposed_conclusion: dict | None = None  # set at the conclusion-review gate
    context_for_engineer: str                # short summary of why these questions
    asked_at: datetime
    agent_name: str                          # "planning" | "gather" | "rca"


class HitlAnswer(JsonModel):
    question_id: UUID
    answer: str
    chosen_candidate: dict | None = None     # when answering a candidate-shortlist question


class PlanEdit(JsonModel):
    op: Literal["add_step", "remove_step", "modify_step", "note"]
    step_id: UUID | None = None
    step: dict | None = None                 # new/modified PlanStep fields
    note: str | None = None


class ConclusionEdit(JsonModel):
    field_path: str                          # e.g. "primary_hypothesis.narrative"
    after: Any
    note: str | None = None


class HitlResponse(JsonModel):
    turn_id: UUID
    answers: list[HitlAnswer] = Field(default_factory=list)         # one per question
    plan_edits: list[PlanEdit] | None = None         # for plan-approval turns
    conclusion_edits: list[ConclusionEdit] | None = None  # for conclusion-review turns
    approved: bool | None = None             # for approval turns
    actions_approved: bool | None = None     # conclusion-review: approve recommended actions for WO
    engineer_notes: str | None = None
    responded_by: str                        # engineer user id (email) — G13
    responded_at: datetime
