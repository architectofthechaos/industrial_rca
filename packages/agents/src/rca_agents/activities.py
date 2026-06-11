"""Temporal activities for the probe (Sprint 3 WI2 §2.3 + WI6).

Each agent leg runs in ``run_agent_leg`` (build agent -> LegContext -> run leg -> persist
evidence/conclusion -> snapshot probe_memory -> return AgentLegResult). The close phase
(``persist_conclusion_to_kg``, ``create_followup_wo``, ``finalize_probe_run``) is deterministic
and HITL-free. Deps are injected at worker startup (onboarding's ``set_activity_deps`` pattern)
so the whole thing is hermetically testable with in-memory repos + a scripted LLM.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from rca_contracts import (
    AgentLegResult,
    EvidencePackage,
    RcaConclusion,
    TokenBudget,
)
from temporalio import activity

from .base import Agent, LegContext
from .models import (
    CreateWoInput,
    FinalizeInput,
    InitProbeInput,
    PersistConclusionInput,
    RunLegInput,
)
from .repos import (
    EvidencePackageRepo,
    ProbeMemoryRepo,
    ProbeRunsRepo,
    RcaConclusionRepo,
)
from .toolbox import ToolBox


class WorkOrderCreator(Protocol):
    async def create(self, *, canonical_id: str, description: str, priority: str,
                     work_type: str, references: dict, requested_by: str,
                     reported_at: datetime) -> dict: ...


@dataclass
class ProbeActivityDeps:
    llm: Any                                    # rca_llm.LLMClient
    toolbox: ToolBox
    asset_graph: Any                            # rca_kg.assets.AssetGraph
    wo_creator: WorkOrderCreator
    runs: ProbeRunsRepo
    memory: ProbeMemoryRepo
    evidence: EvidencePackageRepo
    conclusions: RcaConclusionRepo
    agent_factories: dict[str, Callable[[], Agent]]


_DEPS: ProbeActivityDeps | None = None


def set_activity_deps(deps: ProbeActivityDeps) -> None:
    global _DEPS
    _DEPS = deps


def _deps() -> ProbeActivityDeps:
    if _DEPS is None:
        raise RuntimeError("probe activity deps not set; call set_activity_deps() at startup")
    return _DEPS


def failure_event_id_for(conclusion_id: str) -> str:
    """Deterministic event id from conclusion_id => idempotent KG persist (§6.2)."""
    return str(uuid5(NAMESPACE_URL, f"failure_event:{conclusion_id}"))


# --------------------------------------------------------------------- impls
async def _init_probe_run_impl(deps: ProbeActivityDeps, inp: InitProbeInput) -> None:
    await deps.runs.create_run(
        probe_run_id=UUID(inp.probe_run_id), workflow_id=inp.workflow_id, plant_id=inp.plant_id,
        prompt=inp.prompt, reference_time=inp.reference_time, requested_by=inp.requested_by,
        started_at=inp.started_at)


async def _run_agent_leg_impl(deps: ProbeActivityDeps, inp: RunLegInput) -> AgentLegResult:
    probe_run_id = UUID(inp.probe_run_id)
    agent = deps.agent_factories[inp.agent_name]()
    ctx = LegContext(
        probe_run_id=probe_run_id, correlation_id=inp.correlation_id,
        reference_time=inp.reference_time, plant_id=inp.plant_id, prompt=inp.prompt,
        requested_by=inp.requested_by, llm=deps.llm, toolbox=deps.toolbox, budget=inp.budget,
        replay_from_cache=inp.replay_from_cache)
    leg = await agent.run_leg(graph_state=inp.graph_state, hitl_response=inp.hitl_response,
                              ctx=ctx)

    # persist the durable artifacts a completed leg produced
    if not leg.needs_hitl and leg.final_output:
        if inp.agent_name == "gather" and "evidence_package" in leg.final_output:
            await deps.evidence.put(
                EvidencePackage.model_validate(leg.final_output["evidence_package"]))
        elif inp.agent_name == "rca" and "conclusion" in leg.final_output:
            conclusion = RcaConclusion.model_validate(leg.final_output["conclusion"])
            status = (conclusion.engineer_approval_status
                      or leg.final_output.get("status", "proposed"))
            await deps.conclusions.put(conclusion, status=status)

    # snapshot probe_memory (layer 2): plan, scratchpad, token usage, conversation
    snapshot: dict[str, Any] = {
        "new_messages": [m.model_dump(mode="json") for m in leg.new_messages],
        "token_usage": (leg.token_usage_delta.model_dump()),
    }
    plan = (leg.graph_state or {}).get("plan")
    if plan is not None:
        snapshot["current_plan"] = plan
        snapshot["plan_version_added"] = plan
    if leg.final_output:
        snapshot["working_knowledge"] = {"final_output_keys": sorted(leg.final_output)}
    await deps.memory.snapshot(probe_run_id, snapshot)
    if leg.hitl_turn is not None:
        await deps.memory.append_turn(probe_run_id, leg.hitl_turn.model_dump(mode="json"))
    if inp.hitl_response is not None:
        await deps.memory.append_response(probe_run_id, inp.hitl_response.model_dump(mode="json"))
    return leg


async def _persist_conclusion_to_kg_impl(deps: ProbeActivityDeps,
                                         inp: PersistConclusionInput) -> str:
    c = RcaConclusion.model_validate(inp.conclusion)
    event_id = failure_event_id_for(str(c.conclusion_id))
    h = c.primary_hypothesis
    await deps.asset_graph.persist_failure_event(
        event_id=event_id, probe_run_id=str(c.probe_run_id), conclusion_id=str(c.conclusion_id),
        canonical_id=c.canonical_id, iso14224_failure_mode=h.iso14224_failure_mode,
        iso14224_mechanism=h.iso14224_mechanism, iso14224_cause=h.iso14224_cause,
        narrative=h.narrative, confidence=h.confidence, detected_at=inp.reference_time,
        concluded_at=c.finalized_at or inp.reference_time,
        engineer_approval_status=c.engineer_approval_status or "approved")
    return event_id


async def _create_followup_wo_impl(deps: ProbeActivityDeps, inp: CreateWoInput) -> dict:
    c = RcaConclusion.model_validate(inp.conclusion)
    action = c.recommended_actions[0]
    work_type = {"immediate": "CM", "next_shutdown": "CM", "monitor": "INSPECTION"}.get(
        action.priority, "CM")
    refs = {"probe_run_id": str(c.probe_run_id), "conclusion_id": str(c.conclusion_id),
            "failure_event_id": inp.failure_event_id}
    wo = await deps.wo_creator.create(
        canonical_id=c.canonical_id, description=action.action, priority=action.priority,
        work_type=work_type, references=refs, requested_by=inp.requested_by,
        reported_at=inp.reference_time)
    wo_id = wo.get("work_order_id")
    if wo_id:
        await deps.asset_graph.link_resulted_in_wo(event_id=inp.failure_event_id,
                                                   work_order_id=wo_id)
    return wo


async def _finalize_probe_run_impl(deps: ProbeActivityDeps, inp: FinalizeInput) -> None:
    await deps.runs.update_status(
        UUID(inp.probe_run_id), status=inp.status, phase="closed",
        final_canonical_id=inp.final_canonical_id, token_usage=inp.token_usage,
        errors=inp.errors, completed_at=inp.completed_at)


# --------------------------------------------------------------------- activity wrappers
@activity.defn
async def init_probe_run(inp: InitProbeInput) -> None:
    return await _init_probe_run_impl(_deps(), inp)


@activity.defn
async def run_agent_leg(inp: RunLegInput) -> AgentLegResult:
    return await _run_agent_leg_impl(_deps(), inp)


@activity.defn
async def persist_conclusion_to_kg(inp: PersistConclusionInput) -> str:
    return await _persist_conclusion_to_kg_impl(_deps(), inp)


@activity.defn
async def create_followup_wo(inp: CreateWoInput) -> dict:
    return await _create_followup_wo_impl(_deps(), inp)


@activity.defn
async def finalize_probe_run(inp: FinalizeInput) -> None:
    return await _finalize_probe_run_impl(_deps(), inp)


ALL_ACTIVITIES: list[Callable[..., Any]] = [
    init_probe_run, run_agent_leg, persist_conclusion_to_kg, create_followup_wo,
    finalize_probe_run]

__all__ = [
    "ProbeActivityDeps", "WorkOrderCreator", "set_activity_deps", "ALL_ACTIVITIES",
    "init_probe_run", "run_agent_leg", "persist_conclusion_to_kg", "create_followup_wo",
    "finalize_probe_run", "failure_event_id_for", "TokenBudget",
]
