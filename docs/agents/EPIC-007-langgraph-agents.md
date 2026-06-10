# EPIC-007: LangGraph Tier Agents

**Goal**: One LangGraph graph per tier, executed inside Temporal activities per [SPEC-006](SPEC-006-agent-tier-graphs.md).

**Duration**: Week 6–9

## Stories

### S7.1 — Agent host activity
- Temporal activity `run_agent_tier(tier, probe_state)` that instantiates the right LangGraph.
- Postgres checkpointer for intra-activity resume.
- Budget enforcement at LLM call boundary.

**DoD**: Activity runs an empty graph to completion.

### S7.2 — Scope-tier graph
- Nodes per SPEC-006.
- Tool catalog bound to scope-tier MCP servers.
- Halt on unresolved tags.

**DoD**: For each scenario, the scope-tier graph completes with correct asset, class, window, and signals resolved.

### S7.3 — Evidence-tier graph
- Collection plan → parallel fetch → assemble → validate.
- Bundle persisted; summary returned.

**DoD**: For each scenario, the bundle matches expected components and time alignment.

### S7.4 — Reason-tier graph
- Failure mode scoring + ranking.
- Cause map construction with methodology scaffold.
- Inconclusiveness assessment.

**DoD**: For each scenario, top candidate above min_confidence and cause map structurally valid.

### S7.5 — Govern-tier graph
- Mostly procedural; orchestrates HITL gates.
- Apply reviewer edits to cause map.

**DoD**: End-to-end probe completes through write-back.

### S7.6 — Prompt management
- Versioned prompt templates per node.
- Snapshot prompts at probe start; reuse across retries.

**DoD**: Same probe replays produce identical prompts.

### S7.7 — Model abstraction
- Default Claude Sonnet via Anthropic API.
- Pluggable: GPT-4-class fallback configurable per tenant.

**DoD**: Tenant-level model override works.
