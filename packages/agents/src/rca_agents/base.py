"""Agent-leg foundation (Sprint 3 WI2 §2.2).

The ``Agent`` protocol is the durable boundary the whole probe is built on: a leg runs from
one pause point to the next and returns an ``AgentLegResult`` whose ``graph_state`` (a plain
JSON-serializable dict) is the only thing carried forward — through Temporal event history,
not in-process. This is exactly the seam the WI5 engine-swap test relies on: any object with a
``run_leg`` is a drop-in agent.

The planning/gather/RCA agents are organized as discrete node functions dispatched on
``graph_state["phase"]`` — the same node decomposition a LangGraph ``StateGraph`` would use, so
wrapping them in a live graph (the ``graph`` extra) is a mechanical adapter, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from rca_contracts import AgentLegResult, HitlResponse, TokenBudget
from rca_llm import LLMClient

from .toolbox import ToolBox


def det_uuid(probe_run_id: UUID, *parts: str) -> UUID:
    """Deterministic id from probe_run_id + discriminators. Agent-minted ids (plans, steps,
    turns, conclusions) use this so a replay with the same inputs is byte-identical
    (cross-cutting acceptance #15) — uuid4 would differ every run."""
    return uuid5(NAMESPACE_URL, f"{probe_run_id}:" + ":".join(parts))


@dataclass
class LegContext:
    """Everything a leg needs that isn't in graph_state. Built fresh per activity."""

    probe_run_id: UUID
    correlation_id: str
    reference_time: datetime
    plant_id: str
    prompt: str
    requested_by: str
    llm: LLMClient
    toolbox: ToolBox
    budget: TokenBudget
    replay_from_cache: bool = False


class Agent(Protocol):
    async def run_leg(
        self, *, graph_state: dict | None, hitl_response: HitlResponse | None, ctx: LegContext,
    ) -> AgentLegResult: ...


def new_state(agent_name: str, initial_phase: str) -> dict:
    return {"agent": agent_name, "phase": initial_phase}


__all__ = ["Agent", "LegContext", "new_state", "AgentLegResult", "det_uuid"]
