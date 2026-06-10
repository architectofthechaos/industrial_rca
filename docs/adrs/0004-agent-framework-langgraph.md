# ADR-0004: LangGraph for agent reasoning, hosted inside Temporal activities

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

Inside each tier of a probe, we need an agentic decision loop: the agent looks at current state, decides which MCP tool to call next (bounded to that tier's tool catalog), invokes it, observes the result, and either continues or hands off to the next tier. Temporal handles durable execution and HITL gates but is not an agent framework — it does not natively manage tool catalogs, prompt construction, or reasoning loops.

## Decision

Use **LangGraph** for agent reasoning, executed inside Temporal activities.

- Each tier has its own LangGraph graph definition.
- A Temporal activity called `run_agent_tier(tier, probe_state)` instantiates the graph, runs it to completion (or to a HITL gate), and returns the resulting state.
- LangGraph's built-in Postgres checkpointer is used for *intra-activity* checkpointing so a long agent loop can resume within an activity attempt; durable cross-attempt and cross-process recovery is owned by Temporal.
- Tool calls within LangGraph are wrapped in retry-safe Temporal activity invocations (`workflow.execute_activity` is not callable from inside an activity, so we use a thin RPC layer that re-enters Temporal via a child workflow when a tool call needs strong durability guarantees; most tool calls do not need this and are direct).

## Alternatives considered

**A. Claude Agent SDK (Anthropic) directly.** Strong fit for Claude-only workflows. Rejected for MVP only because LangGraph is model-agnostic, which keeps us from locking to Anthropic before pricing and capability shake out. We may swap to Claude Agent SDK in v2.

**B. Pure prompting with function-calling, no framework.** Rejected — we need graph control flow (conditional edges, branching, parallel tool calls) that is tedious to hand-roll.

**C. CrewAI / AutoGen multi-agent.** Rejected — multi-agent adds coordination complexity we do not need. One graph per tier is simpler and more debuggable.

**D. LangGraph alone, no Temporal.** Rejected per [ADR-0003](0003-workflow-engine-temporal.md).

## Consequences

**Positive:**

- Clean separation: Temporal owns durability, LangGraph owns reasoning.
- Each tier graph is small (5–15 nodes), easy to read and modify.
- Tool catalog is bounded per tier — agent cannot call cross-tier tools by accident.
- Model swap (Claude → other) is contained to LangGraph node definitions.

**Negative:**

- Two frameworks to learn and operate.
- Determinism: LangGraph itself is non-deterministic (LLM calls); we must ensure non-deterministic behavior stays within activities, not workflow code.
- Glue code between Temporal payloads and LangGraph state requires care.

## References

- LangGraph: https://langchain-ai.github.io/langgraph/
- [ADR-0003 Temporal](0003-workflow-engine-temporal.md)
- [SPEC-006 Agent Tier Graphs](../agents/SPEC-006-agent-tier-graphs.md)
