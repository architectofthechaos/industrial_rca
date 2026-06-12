"""Probe workflow I/O models (Sprint 3 WI2/WI3)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from rca_contracts import HitlResponse, TokenBudget


class ProbeWorkflowInput(BaseModel):
    prompt: str
    plant_id: str | None = None
    reference_time: datetime | None = None     # frozen to workflow start when omitted (G10)
    requested_by: str
    probe_run_id: str | None = None            # API mints it so it can 202-return it (G10/G11)
    # Defaults sized for a full real-LLM probe (Sprint 5 G27): a live Opus run re-sends the
    # evidence package across planning+gather+fishbone+gaps+~7 five-whys+rank (~85k input observed),
    # which blew the old hermetic-sized 50k/10k budget and tripped budget_exceeded mid-probe.
    input_tokens_limit: int = 400000
    output_tokens_limit: int = 50000


class ProbeResult(BaseModel):
    probe_run_id: str
    workflow_id: str
    status: str                                 # ProbeRunStatus value
    canonical_id: str | None = None
    conclusion_id: str | None = None
    failure_event_id: str | None = None
    followup_wo_id: str | None = None
    wo_creation_status: str | None = None
    token_usage: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)


# --- activity I/O ---
class RunLegInput(BaseModel):
    probe_run_id: str
    agent_name: str                             # "planning" | "gather" | "rca"
    graph_state: dict | None = None
    hitl_response: HitlResponse | None = None
    correlation_id: str
    budget: TokenBudget
    reference_time: datetime
    plant_id: str
    prompt: str
    requested_by: str
    replay_from_cache: bool = False


class InitProbeInput(BaseModel):
    probe_run_id: str
    workflow_id: str
    plant_id: str
    prompt: str
    reference_time: datetime
    requested_by: str
    started_at: datetime


class FinalizeInput(BaseModel):
    probe_run_id: str
    status: str
    final_canonical_id: str | None = None
    token_usage: dict = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
    completed_at: datetime


class PersistConclusionInput(BaseModel):
    conclusion: dict                            # RcaConclusion payload
    reference_time: datetime


class CreateWoInput(BaseModel):
    conclusion: dict
    failure_event_id: str
    requested_by: str
    reference_time: datetime


__all__ = [
    "ProbeWorkflowInput", "ProbeResult", "RunLegInput", "InitProbeInput", "FinalizeInput",
    "PersistConclusionInput", "CreateWoInput",
]
