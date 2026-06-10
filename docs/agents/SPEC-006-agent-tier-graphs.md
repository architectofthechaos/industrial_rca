# SPEC-006: Agent Tier Graphs (LangGraph)

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0004](../adrs/0004-agent-framework-langgraph.md)

## Purpose

Defines the LangGraph graph for each tier: nodes, edges, state shape, and tool catalog binding.

## Common state shape

```python
class TierState(BaseModel):
    probe_id: UUID
    tenant_id: UUID
    tier: Literal["scope", "evidence", "reason", "govern"]
    template_version: str
    inputs: dict
    scratchpad: list[ToolCallRecord] = []
    outputs: dict = {}
    halt_reason: str | None = None     # set to non-null to halt before completion (e.g., HITL)
    budget_used_usd: float = 0.0
    budget_limit_usd: float
```

## Scope tier graph

Nodes:
1. `resolve_asset` — call `assets.resolve` with trigger payload.
2. `classify_class` — call `assets.classify_iso14224`.
3. `load_template` — call `templates.load`.
4. `build_neighborhood` — call `kg.get_neighborhood`.
5. `set_window` — call `probe.set_time_window` using template defaults + trigger context.
6. `resolve_critical_tags` — for each `required_signal` in template, call `trs.search_signals`; pause if any unresolved with confidence < threshold.

Edges: linear with a conditional from `resolve_critical_tags` → halt(`tag_confirmation_needed`) if any unresolved.

## Evidence tier graph

Nodes:
1. `plan_collection` — agent inspects template's evidence recipes and produces a parallel collection plan.
2. `parallel_fetch` — execute the plan: a fan-out over `pi.get_series`, `maximo.get_workorders`, `documents.search`, etc.
3. `assemble_bundle` — combine returns into a single `EvidenceBundle`, write to object storage.
4. `validate_bundle` — assert all required signals present, time windows aligned, provenance complete.
5. `summarize_for_reason` — produce a compact summary (signal stats, key events) for the next tier; full bundle stays in object storage.

Edges: 1 → 2 → 3 → 4; 4 → 2 (re-fetch) on validation failure (bounded retries); 4 → 5 on success.

## Reason tier graph

Nodes:
1. `score_failure_modes` — for each failure mode in template, call `evidence.score_failure_mode`.
2. `rank_candidates` — sort by posterior; agent reviews top-K.
3. `select_methodology` — pick 5-whys / fishbone / FTA / PROACT based on top candidate's complexity.
4. `build_cause_map` — iterative: create_node / create_edge / attach_evidence based on the methodology scaffold.
5. `assess_inconclusiveness` — if top candidate score < threshold, set `halt_reason="inconclusive_expand_neighborhood"`.
6. `finalize` — emit `ReasonResult`.

## Govern tier graph

Mostly procedural — agent has a smaller role here, mostly orchestrating HITL gates.

Nodes:
1. `submit_for_review` — emit HITL request.
2. `await_review` — handled by Temporal signal, not LangGraph itself.
3. `apply_edits` — if reviewer edited, update cause map and propagate to provenance.
4. `preview_cmms` — call `cmms.preview_writeback`.
5. `request_writeback_auth` — second HITL gate.
6. `commit_cmms` — call `cmms.commit_writeback` after authorization.
7. `index_corpus` — call `corpus.index_probe`.
8. `propose_overlay_update` — call `overlay.propose_update`; auto-commit for stat-only, HITL for structural.

## Tool catalog binding

Each tier graph is instantiated with a tool registry limited to its tier's MCP server URLs:

```python
scope_tools = MultiServerMCPClient([
    "trs", "assets", "kg", "templates", "probe",
]).get_tools()

evidence_tools = MultiServerMCPClient([
    "pi", "dcs", "alarms", "maximo", "sap_pm", "documents", "vibration", "lab",
]).get_tools()
```

The agent cannot call cross-tier tools by construction — they are not in its bound catalog.

## Budget enforcement

Each node wraps its LLM call in a budget check; if `budget_used_usd + estimated_cost > budget_limit_usd`, the node halts with `budget_exceeded`.

## Determinism boundaries

LangGraph nodes that call LLMs or external services are non-deterministic. They run *inside* Temporal activities. The graph's structural edges are deterministic and replayable.

## Checkpointing

LangGraph uses Postgres checkpointer for intra-activity resume (if an LLM call fails partway through a multi-tool node). Cross-activity / cross-process resume is owned by Temporal.
