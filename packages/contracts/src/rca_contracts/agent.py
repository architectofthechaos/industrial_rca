"""Agent-leg contract (Sprint 3 WI2).

The "leg" is the unit of LangGraph execution between two pause points. A leg runs
inside one Temporal activity, from probe start (or HITL resume) until the next HITL
pause or completion. LangGraph state serializes through the activity result.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from ._base import StrictModel
from .agent_io import TokenUsage
from .hitl import HitlResponse, HitlTurn

AgentName = Literal["planning", "gather", "rca"]


class Message(StrictModel):
    """Serializable representation of a conversation/scratchpad message.

    LangChain message objects serialize awkwardly through Temporal (risk #10); the
    tool adapter converts to/from this flat shape at the leg boundary.
    """

    role: str                       # "system" | "user" | "assistant" | "tool"
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class AgentLegResult(StrictModel):
    needs_hitl: bool
    hitl_turn: HitlTurn | None = None       # questions + context to show engineer
    final_output: dict | None = None        # set when the leg completes (plan / evidence / conclusion)
    graph_state: dict = Field(default_factory=dict)   # serialized for the next leg
    new_messages: list[Message] = Field(default_factory=list)  # appended to agent_scratchpad
    new_llm_call_ids: list[UUID] = Field(default_factory=list)  # for audit linkage
    token_usage_delta: TokenUsage = Field(default_factory=TokenUsage)
    graph_state_ref: str | None = None       # set instead of graph_state when state spills (2.5)


__all__ = ["AgentName", "Message", "AgentLegResult", "HitlResponse", "HitlTurn"]
