# Sprint 3 Spec — End-to-End Probe (Three Agents, HITL, RCA Conclusion)

**Sprint goal:** Ship the first end-to-end probe loop. A Temporal workflow represents one full probe, orchestrating **three LangGraph agents** (planning, gather, RCA) plus a deterministic close phase. The probe goes from a user's natural-language prompt → planning (with HITL Q&A and plan approval) → evidence gathering (with HITL for scope changes) → assembly of a structured Evidence Package → RCA analysis (fishbone + 5 Whys + hypothesis ranking, with HITL for evidence gaps and conclusion review) → KG persistence and follow-up WO. The RCA agent is a LangGraph agent in our codebase for the prototype; the `EvidencePackage`→`RcaConclusion` contract is the long-term boundary that a partner-supplied engine could later sit behind without changing the workflow.

**Audited against:** `rca_phase1_data_layer_spec.md`, `rca_platform_consolidated_context.md`, `rca_use_case_adil.md`, `sprint2_state_report.md`.

**Prerequisites:** Sprint 2b complete (Connections API, Onboarding workflow, six entity MCPs, Resolution Queue write paths, Temporal cluster running).

**Scope (6 work items):**
1. LLM client + prompt registry (foundation for all AI calls)
2. LangGraph agent foundation + probe-level memory (3-layer storage)
3. Planning agent + HITL Q&A and plan approval (Temporal signals)
4. Gather agent + lazy KG materialization + Evidence Package assembly
5. RCA agent + fishbone + 5 Whys + hypothesis ranking + conclusion-review HITL (`RcaConclusion`)
6. KG persistence (`HistoricalFailureEvent`) + follow-up WO creation

## Architectural decisions baked into this spec

Override any you disagree with.

1. **Temporal owns the probe lifecycle end-to-end.** One Temporal workflow = one probe. The workflow does not complete until the engine returns the conclusion, the engineer approves it, and the follow-up WO (if any) is created.
2. **LangGraph runs inside Temporal activities, one leg per activity.** Each "leg" runs from probe start (or HITL resume) until the next pause point or completion. LangGraph state serializes through activity results.
3. **HITL is a bidirectional channel, not just approval.** Agents can ask clarifying questions, request context, propose scope changes, or request approval. Relevant questions are batched per turn to minimize round trips.
4. **HITL bridge:** Temporal `wait_condition` + workflow signal. The FastAPI endpoint receives the engineer's response and signals the workflow. LangGraph does NOT signal Temporal directly.
5. **Probe memory lives in three layers:** (1) Temporal event history (authoritative, durable, automatic), (2) Postgres `probe_memory` snapshot (UI reads), (3) LangGraph in-memory checkpointer (ephemeral, per-activity). 1-month retention on Postgres snapshot post-completion, then archive.
6. **The RCA analysis runs as a third LangGraph agent in our codebase** (`packages/agents/rca_graph.py`), using the same leg pattern as planning and gather. The `EvidencePackage`→`RcaConclusion` contract is the long-term boundary — a partner-supplied engine can later replace our agent behind the same activity without workflow changes.
7. **Failure modes are outputs, not inputs.** The user describes symptoms; the platform produces a candidate shortlist; the engine produces ranked hypotheses.
8. **No RAG over external corpora** (Phase 2). Grounding is Evidence Package + KG.
9. **KG Asset retention:** lazy upsert, no TTL.
10. **Cold-start friendly:** the first probe on a plant with an empty KG asks more HITL questions; the agent batches them aggressively.

---

## Work Item 1 — LLM Client + Prompt Registry

**Goal:** A single non-bypassable abstraction every LLM call goes through. Provenance, caching, and budget enforcement guaranteed. Used by all three LangGraph agents (planning, gather, RCA) and the intent parser.

### 1.1 Package layout

`packages/llm/`:
- `client.py` — `LLMClient` interface + `AnthropicClient` implementation
- `prompts/` — versioned prompt templates (Markdown + YAML frontmatter)
- `registry.py` — loads prompts at startup, validates schema, exposes `get_prompt(name, version)`
- `audit.py` — writes to `llm_calls` table
- `cache.py` — content-addressed cache (`prompt_hash` → response) for replay
- `budget.py` — per-probe token budget tracking

### 1.2 `LLMClient` interface

```python
class LLMClient(Protocol):
    async def complete(
        self,
        prompt_name: str,
        prompt_version: str,
        variables: dict[str, Any],
        *,
        correlation_id: str,
        budget: TokenBudget | None = None,
        replay_from_cache: bool = False,
    ) -> LLMResponse: ...

    async def embed(
        self,
        text: str | list[str],
        *,
        model: str = "voyage-3",
        correlation_id: str,
    ) -> list[list[float]]: ...
```

**Return shape:**
```python
class LLMResponse(BaseModel):
    content: str
    structured: dict | None       # parsed JSON if prompt declares output_schema
    model: str
    model_version: str
    prompt_hash: str              # SHA-256 of rendered prompt
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool
    llm_call_id: UUID
```

### 1.3 Prompt template format

Markdown with YAML frontmatter declaring `name`, `version`, `model`, `temperature`, `max_tokens`, `output_schema`, `variables`. Registry validates that template body references match declared variables and that `output_schema` is a valid JSON schema.

### 1.4 `llm_calls` audit table

| Column | Type | Notes |
|---|---|---|
| `llm_call_id` | UUID | PK |
| `correlation_id` | TEXT | Indexed |
| `probe_run_id` | UUID | NULL for non-probe calls, indexed |
| `prompt_name` / `prompt_version` / `prompt_hash` | TEXT | |
| `model` / `model_version` | TEXT | |
| `temperature` | FLOAT | |
| `input_tokens` / `output_tokens` | INT | |
| `latency_ms` | INT | |
| `cached` | BOOL | |
| `request_payload` / `response_payload` | JSONB | |
| `created_at` | TIMESTAMPTZ | |

### 1.5 Budget enforcement

```python
class TokenBudget(BaseModel):
    input_tokens_limit: int = 50000
    output_tokens_limit: int = 10000
    input_used: int = 0
    output_used: int = 0
```

`LLMClient.complete` raises `TokenBudgetExceeded` (workflow-friendly) when a call would exceed the limit. The workflow catches and emits a partial result with `coverage.llm_status='budget_exceeded'`.

### 1.6 Secret handling

`ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` resolved via the existing `EnvSecretResolver`. Same pattern as connector auth.

### 1.7 Acceptance

- `LLMClient.complete` returns full provenance on every call
- Same inputs + `replay_from_cache=True` → cached response, no upstream API call
- Budget overrun raises `TokenBudgetExceeded`; workflow handles gracefully
- `llm_calls` audited with prompt_hash, token counts, and `probe_run_id` when applicable
- Prompt registry rejects prompts whose declared `variables` don't match the body
- pgvector provisioned in Postgres compose; `document_embeddings` table exists

---

## Work Item 2 — LangGraph Agent Foundation + Probe Memory

**Goal:** Reusable LangGraph scaffolding for agents that run inside Temporal activities, plus the 3-layer probe memory model. The planning agent (WI3), gather agent (WI4), and RCA agent (WI5) all build on this.

### 2.1 Package layout

`packages/agents/`:
- `base.py` — `AgentLegResult` shape, `serialize_state` / `deserialize_state` helpers, shared graph utilities
- `memory.py` — probe memory read/write, snapshotting to Postgres, conversation log management
- `tools.py` — adapter that exposes our MCP tools (kg.*, asset.*, tag.*, work_order.*, document.*, operator_log.*, connections.*) as LangChain tools. Tools route through the existing MCP servers — no direct DB access from agents.
- `planning_graph.py` — planning agent (WI3)
- `gather_graph.py` — gather agent (WI4)
- `rca_graph.py` — RCA agent (WI5)
- `nodes/` — shared graph nodes (hitl_ask, hitl_resume, llm_call, tool_call, summarize_state)

### 2.2 The "leg" pattern

A LangGraph leg runs from one pause point to the next:

```python
class AgentLegResult(BaseModel):
    needs_hitl: bool
    hitl_turn: HitlTurn | None       # questions + context to show engineer
    final_output: dict | None        # set when leg completes (e.g. final plan, final evidence)
    graph_state: dict                # serialized for next leg
    new_messages: list[Message]      # appended to probe_memory.agent_scratchpad
    new_llm_call_ids: list[UUID]     # for audit linkage
    token_usage_delta: TokenUsage    # accumulated this leg

class HitlTurn(BaseModel):
    turn_id: UUID
    questions: list[HitlQuestion]    # batched, relevant questions in one turn
    proposed_plan: dict | None       # when at plan-approval gate
    proposed_conclusion: dict | None # when at conclusion-review gate
    context_for_engineer: str        # short summary of why these questions
    asked_at: datetime
```

```python
class HitlQuestion(BaseModel):
    question_id: UUID
    text: str
    question_type: str               # "clarification" | "context" | "scope" | "approval"
    candidates: list[dict] | None    # e.g. asset shortlist when asking which pump
    required: bool = True
```

### 2.3 Activity contract

Every agent leg is invoked as a Temporal activity with this shape:

```python
@activity.defn
async def run_agent_leg(
    *,
    probe_run_id: UUID,
    agent_name: str,                 # "planning" | "gather" | "rca"
    graph_state: dict | None,        # None on first leg
    hitl_response: HitlResponse | None,
    correlation_id: str,
    budget: TokenBudget,
    replay_from_cache: bool = False,
) -> AgentLegResult: ...
```

The activity:
1. Rehydrates or initializes the LangGraph state
2. Injects the HITL response if present
3. Runs the graph until it pauses for HITL or completes
4. Snapshots probe memory to Postgres
5. Returns `AgentLegResult` with serialized state

### 2.4 Probe memory — three layers

**Layer 1: Temporal event history.** Automatic. Every activity's input (including prior `graph_state`) and output (including new `graph_state`) is durably stored by Temporal. Source of truth for "what happened in this probe."

**Layer 2: Postgres `probe_memory` table** (UI snapshot):

```sql
CREATE TABLE probe_memory (
    probe_run_id UUID PRIMARY KEY REFERENCES probe_runs(probe_run_id),
    conversation JSONB NOT NULL,           -- ordered list of HitlTurn + HitlResponse pairs
    current_plan JSONB,                    -- latest investigation plan version
    plan_history JSONB,                    -- prior plan versions
    working_knowledge JSONB,               -- resolved asset, candidate failure modes, etc.
    agent_scratchpad JSONB,                -- LangGraph message history for display
    token_usage JSONB,                     -- cumulative across all legs
    last_updated_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ                -- set 1 month after probe completion
);
```

Written at the end of every agent-leg activity. Read by FastAPI endpoints serving the engineer's UI.

**Layer 3: LangGraph in-memory checkpointer.** Lives within a single activity execution. We use the in-memory checkpointer — NOT the Postgres one. Durability comes from Temporal. Serialized state passes through activity results.

### 2.5 Large state escape hatch

Default path: serialized graph state passes through Temporal activity results (~limit 2 MB). If state grows past a threshold (e.g. 500 KB), the leg writes the heavy state to a `probe_graph_state` table keyed by `probe_run_id` and returns a reference instead. Next leg fetches by reference. Refplant scale won't hit this; we ship the table but don't exercise it.

### 2.6 Tool adapters

All MCP tools available to agents through LangChain-compatible wrappers in `packages/agents/tools.py`. Every tool call goes through the existing MCP servers (HTTP). No direct DB or KG access from agents. Tool results carry provenance (connection_id, timestamps) for the Evidence Package.

### 2.7 Memory retention

- Probe memory snapshot retained in Postgres for **1 month after probe completion** (`status='completed'`)
- After 1 month, `archived_at` is set and the JSONB columns are nulled out (a separate `probe_memory_archive` table preserves a compressed form for compliance, if needed — Phase 2)
- Temporal event history retention follows Temporal's namespace policy (default 30 days; can be extended)

### 2.8 Acceptance

- `packages/agents/` package exists with the leg-pattern foundation
- `run_agent_leg` activity contract works for a trivial test graph (round-trip serialize/deserialize)
- `probe_memory` table exists; snapshot is written at end of every leg
- A test confirms the same probe can run leg → wait for signal → leg again, with state preserved through Temporal alone (no Postgres dependency for state passing)
- A test confirms an oversize state spills to `probe_graph_state` and is rehydrated by the next leg
- Conversation log persists every HITL turn with question and engineer response
- 1-month retention job exists (Postgres `pg_cron` or a Temporal cron workflow — pick `pg_cron`)
- Tool adapters expose all **19** existing MCP tools through LangChain interface (corrected from "20" — see Gap Resolution G1; Sprint 3 adds 4 more for a post-sprint total of 23)

---

## Work Item 3 — Planning Agent + Plan Approval HITL

**Goal:** A LangGraph agent that takes the user's prompt, resolves intent, builds a candidate failure mode shortlist, drafts an evidence-gathering plan, and reaches consensus with the engineer through bidirectional HITL.

### 3.1 Planning agent graph shape

Nodes (LangGraph):

1. **parse_intent** — LLM call (`parse_probe_intent.md`) → structured intent (asset candidates, suspected symptoms, time window). Uses `tool.asset.search_by_keywords` to ground candidates.
2. **resolve_asset_or_ask** — if asset confidence ≥ 0.85 proceed; otherwise emit a HITL question batching asset choice + any other ambiguities (time window, symptom phrasing) into one turn.
3. **load_kg_context** — calls `kg.get_asset_context` for the resolved asset + applicable failure modes. Cold KG → just ISO 14224 ontology. Warm KG → also prior failure events for asset + class.
4. **build_failure_mode_shortlist** — LLM call (`build_failure_mode_shortlist.md`) → ranked candidate failure modes with reasoning. Grounded in KG context + symptoms.
5. **draft_evidence_plan** — LLM call (`draft_evidence_plan.md`) → structured `InvestigationPlan` (steps: tag history queries, WO lookups, doc searches, log queries, time windows, scope notes). Plan is opinionated, not exhaustive.
6. **propose_plan_to_engineer** — emits a HITL turn with proposed plan + any open questions ("FYI, I'm assuming 7-day lookback; extend if you've seen issues earlier") + an approval question.
7. **apply_plan_edits** — on resume, applies engineer's edits (added/removed/modified steps, notes) to the plan.
8. **finalize_plan** — if engineer approved, emit `final_output={'plan': InvestigationPlan}` and `needs_hitl=False`.
9. **replan** — if engineer rejected or substantially edited and the agent wants to re-propose, loops back to step 5.

### 3.2 Prompts

- `parse_probe_intent.md` (v1) — same as previous spec draft; input is prompt + plant context + asset shortlist
- `build_failure_mode_shortlist.md` (v1) — input is symptoms + asset class + KG failure mode set + prior events (if warm); output is ranked shortlist
- `draft_evidence_plan.md` (v1) — input is asset + shortlist + available connections + KG context; output is `InvestigationPlan`
- `summarize_for_engineer.md` (v1) — used by `propose_plan_to_engineer` to write the engineer-facing context blurb

### 3.3 `InvestigationPlan` schema

```python
class PlanStep(BaseModel):
    step_id: UUID
    step_type: str          # "tag_history" | "work_orders" | "documents" | "operator_logs" | "kg_query"
    description: str        # engineer-readable
    parameters: dict        # step-type-specific (tag list, window, search terms, etc.)
    rationale: str          # why this step
    estimated_cost: str | None  # "fast" | "slow" | "expensive" — qualitative

class InvestigationPlan(BaseModel):
    plan_id: UUID
    probe_run_id: UUID
    version: int            # incremented on each edit cycle
    asset_canonical_id: str
    candidate_failure_modes: list[FailureModeCandidate]   # ranked
    steps: list[PlanStep]
    engineer_notes: str | None    # free text from engineer
    finalized_at: datetime | None
```

### 3.4 HITL behavior

- **Batching:** every HITL turn carries up to all relevant open questions plus the proposed plan (when at the approval gate). Never emit a single-question turn if another related question is pending.
- **Cold start posture:** if the agent detects an empty/sparse KG (no prior probes, no failure events), it asks more context questions up front in the first HITL turn ("Is this pump in normal operation? Any recent maintenance you remember?").
- **Re-plan limit:** max 2 re-plan cycles after engineer rejection; third rejection ends the planning phase with `status='planning_aborted'` and surfaces in API.

### 3.5 Workflow integration

The Temporal workflow runs planning legs in a loop:

```
graph_state = None
hitl_input = None
while True:
    leg = await execute_activity(run_agent_leg, agent_name="planning", graph_state=graph_state, hitl_response=hitl_input, ...)
    graph_state = leg.graph_state
    if not leg.needs_hitl:
        break
    self._pending_hitl_turn = leg.hitl_turn
    persist_hitl_turn_to_probe_memory(leg.hitl_turn)
    await wait_condition(lambda: self._hitl_response is not None)
    hitl_input = self._hitl_response
    self._hitl_response = None
final_plan = leg.final_output['plan']
```

### 3.6 REST API additions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/probes/runs/{id}/hitl/pending` | Returns the current pending `HitlTurn` (or 204 if none) |
| `POST` | `/probes/runs/{id}/hitl/respond` | Body: `HitlResponse`. Signals the workflow. |
| `GET` | `/probes/runs/{id}/plan` | Current investigation plan (latest version) |
| `GET` | `/probes/runs/{id}/plan/history` | All plan versions |

`HitlResponse` shape:

```python
class HitlResponse(BaseModel):
    turn_id: UUID
    answers: list[HitlAnswer]               # one per question
    plan_edits: list[PlanEdit] | None       # for plan-approval turns
    conclusion_edits: list[ConclusionEdit] | None  # for conclusion-review turns
    approved: bool | None                   # for approval turns
    engineer_notes: str | None              # free text
    responded_at: datetime
```

### 3.7 Acceptance

- For prompt `"P-2103A vibration's been climbing for a week"` with an empty KG, the planning agent produces a HITL turn asking ≥1 context question batched with the proposed plan
- For prompt `"the BB1 pump in CDU is noisy"` (ambiguous asset), the first HITL turn asks which pump AND batches any other pending clarifications
- The investigation plan contains ≥3 steps with rationale per step
- Engineer-approved plan transitions probe to gather phase
- Engineer can edit a plan and resubmit; agent applies edits and emits final plan
- Re-plan limit (2) is enforced; third rejection produces `status='planning_aborted'`
- Every HITL turn is persisted to `probe_memory.conversation` with question text and response
- Replay-from-cache produces byte-identical plans for the same prompt + HITL responses

---

## Work Item 4 — Gather Agent + Lazy KG + Evidence Package Assembly

**Goal:** Execute the approved investigation plan: gather raw evidence through MCP tools, lazily materialize the KG Asset layer, perform LLM-driven anomaly detection and document scoring, assemble the canonical Evidence Package. HITL is invoked only for low-confidence resolutions or scope changes the agent wants to propose.

### 4.1 Gather agent graph shape

Nodes:

1. **execute_plan_steps** — iterates through `InvestigationPlan.steps`, calling the appropriate MCP tools. Each step is a tool call; results accumulated in graph state.
2. **detect_low_confidence_resolutions** — if any tag or doc resolution lands below the auto-accept threshold, mark for HITL.
3. **propose_scope_changes_or_ask** — if a step returned empty/sparse results, the agent may propose extending the time window or broadening keywords. Emits a HITL turn batching all such proposals.
4. **materialize_kg** — calls `kg.upsert_asset`, `kg.link_failure_mode` for each candidate mode investigated.
5. **detect_anomalies** — LLM call (`detect_tag_anomalies.md`) on tag summaries; fallback to 3σ rule on LLM failure.
6. **score_documents** — embedding-based cosine similarity using `LLMClient.embed`; fallback to keyword overlap.
7. **assemble_evidence_package** — writes `EvidencePackage` to `evidence_packages` table.

### 4.2 Lazy KG materialization (same as prior spec)

KG schema additions:

**New node label:** `Asset` — `id` (= canonical_id), `name`, `plant_id`, `unit_slug`, `iso14224_class`, `iso14224_class_confidence`, `iso14224_class_method`, `materialized_at`, `last_probed_at`. Per-label uniqueness on `id`.

**New relationships:**
- `(Asset)-[:LOCATED_IN]->(Unit)`
- `(Asset)-[:INSTANCE_OF]->(EquipmentClass)`
- `(Asset)-[:CAN_EXHIBIT]->(FailureMode)` (per-mode-investigated, not Cartesian)

**New KG MCP tools:** `kg.upsert_asset`, `kg.link_failure_mode`, `kg.get_asset_context`. Behavior as in previous draft.

**Migration:** `0004_asset_layer.cypher` — Asset uniqueness constraint + indexes on `plant_id`, `unit_slug`.

### 4.3 Evidence Package schema

```python
class EvidencePackage(BaseModel):
    evidence_package_id: UUID
    probe_run_id: UUID
    canonical_id: str
    investigated_failure_modes: list[str]
    reference_time: datetime
    lookback_hours: int

    # Cold context (from MAR + KG)
    asset: AssetSummary
    location: HierarchyPath
    iso14224_context: ISO14224Context

    # Warm evidence
    tag_evidence: TagEvidence
    work_order_evidence: WorkOrderEvidence
    document_evidence: DocumentEvidence
    operator_log_evidence: OperatorLogEvidence

    # Plan + agent context
    investigation_plan: InvestigationPlan       # the executed plan (final version)
    plan_execution_notes: list[PlanExecutionNote]   # per-step outcomes, deviations

    # Coverage + provenance
    coverage: CoverageReport
    provenance: list[ProvenanceEntry]
    assembled_at: datetime
    schema_version: str = "v1"
```

Sub-shapes (`AssetSummary`, `HierarchyPath`, `ISO14224Context`, `TagEvidence`, `WorkOrderEvidence` etc.) match the prior draft. Key fields:

- `TagEvidence.anomaly_method`: `"llm_v1"` | `"rule:3sigma"`
- `DocumentEvidence.score_method`: `"embedding_v1"` | `"keyword_overlap"`
- `CoverageReport.llm_status`: `"ok"` | `"budget_exceeded"` | `"fallback_used"`

### 4.4 Persistence

`evidence_packages` table — same shape as prior draft (`evidence_package_id`, `probe_run_id`, `canonical_id`, `investigated_failure_modes`, `schema_version`, `payload`, `assembled_at`).

### 4.5 HITL during gather

Less common than planning, but supported:

- **Low-confidence asset resolution** (rare, since planning resolved this) → ask
- **Empty tag history** → ask "extend window?"
- **Document search returned nothing** → propose broader keywords, ask approval
- **Unexpected disconnect** of a connection mid-gather → ask whether to skip category or wait

All batched into a single HITL turn when multiple issues arise simultaneously.

### 4.6 Acceptance

- KG Asset label uniqueness constraint exists; lazy materialization works
- `kg.upsert_asset` is idempotent; `kg.link_failure_mode` rejects invalid (class, mode) pairs
- For the P-2103A scenario, gathering produces an Evidence Package with non-empty sections for every healthy category
- Partial coverage: stopping Maximo mid-gather → `coverage.cmms.status='skipped:connection_unhealthy'`; run continues
- LLM anomaly detection runs; falls back to 3σ on LLM failure with `anomaly_method` updated
- Document embeddings cached in `document_embeddings`; second probe over same docs incurs zero embedding calls
- Plan execution notes capture per-step outcomes (records returned, time taken, deviations)
- A test confirms HITL during gather works: simulate empty tag history → agent asks → engineer extends window → gather resumes with new window

---

## Work Item 5 — RCA Agent (Fishbone + 5 Whys + Hypothesis Ranking + Conclusion Review HITL)

**Goal:** A third LangGraph agent — same leg pattern as planning and gather — that consumes the Evidence Package and produces a structured `RcaConclusion` containing fishbone, 5 Whys, and ranked hypotheses. The agent can pause for HITL when evidence has gaps, when the 5 Whys chain needs human input to advance, and at the final conclusion-review gate. The contract `EvidencePackage` → `RcaConclusion` is the long-term boundary that a partner-supplied engine can later sit behind without changing the workflow.

### 5.1 Package layout

`packages/agents/rca_graph.py` — the RCA agent graph. Same `AgentLegResult` contract and leg pattern as planning/gather (defined in WI2).

Prompts under `packages/llm/prompts/`:
- `rca_build_fishbone.md` (v1)
- `rca_run_five_whys_step.md` (v1) — one prompt per "why" step, iterative
- `rca_detect_evidence_gaps.md` (v1) — decides whether HITL is needed before proceeding
- `rca_rank_hypotheses.md` (v1)
- `rca_summarize_for_engineer.md` (v1) — used by conclusion-review HITL turn

### 5.2 RCA agent graph shape

Nodes:

1. **load_evidence_package** — pull the `EvidencePackage` from Postgres by id. No LLM call.
2. **build_fishbone** — LLM call producing the 6-category fishbone with causes grounded in Evidence Package citations. KG queried for ISO 14224 ontology context.
3. **detect_evidence_gaps_pre_5whys** — LLM call deciding whether the fishbone exposes gaps the engineer should fill before 5 Whys begins (e.g. missing maintenance history, unknown process upset window). If `needs_hitl=true`, emit a HITL turn batching gap questions.
4. **apply_gap_responses** — on resume, ingest engineer's answers into agent scratchpad and proceed.
5. **run_five_whys_loop** — iterative loop:
   - For each "why" step: LLM call (`rca_run_five_whys_step.md`) producing the next question and proposed answer
   - Validate the answer is grounded in Evidence Package or KG; if not, mark for HITL
   - If answer is grounded with high confidence → continue
   - If answer is grounded with low confidence OR requires human knowledge (e.g. "was the operator trained?") → emit a HITL turn with the "why" question
   - Terminate when an answer is a verified root cause OR after a max-depth of 7 whys
6. **rank_hypotheses** — LLM call producing primary + up to 2 alternative hypotheses with KG-validated ISO 14224 codes (failure mode, mechanism, cause). Each hypothesis cites Evidence Package items.
7. **validate_conclusion** — programmatic checks (see §5.5). If validation fails: 1 retry of the failing node; second failure → emit the partial conclusion with `validation_errors` and proceed to engineer review (the engineer can still approve, edit, or reject).
8. **propose_conclusion_to_engineer** — emit a HITL turn with `proposed_conclusion` + summary blurb + approval questions ("Approve the conclusion?", "Approve the recommended actions for follow-up WO?").
9. **apply_engineer_edits** — on resume, apply edits (demoted hypotheses, narrative changes, action list changes). Store `engineer_edits` on the final conclusion.
10. **finalize_conclusion** — emit `final_output={'conclusion': RcaConclusion}` and `needs_hitl=False`.
11. **regenerate_conclusion** — if engineer rejected and the agent has budget remaining, loop back to step 6 (max 1 regeneration after rejection; second rejection → terminate with `status='conclusion_rejected'` and the rejected version persisted for KG flywheel signal).

### 5.3 HITL contexts inside the RCA agent

Three distinct kinds of HITL in this agent — all use the same `HitlTurn` shape, batched when relevant:

1. **Evidence-gap questions** (pre-5-whys, optional) — "I see no record of the last seal replacement on this asset. Do you have a date?"
2. **5 Whys human-knowledge questions** (mid-loop, opportunistic) — "Why did the alignment slip? My evidence doesn't tell me. Was there a recent baseplate shim adjustment?"
3. **Conclusion review** (terminal, always) — "Approve this RCA conclusion? Approve recommended actions?"

Cold-start posture: when the KG has no prior failure events for this asset/class, the agent batches more gap questions up front. Token budget pressure → skip optional gap questions, proceed with available evidence.

### 5.4 `RcaConclusion` schema

```python
class FiveWhysStep(BaseModel):
    rank: int                            # 1, 2, 3, ...
    why_question: str
    answer: str
    answer_source: str                   # "evidence_package" | "kg" | "engineer_hitl" | "agent_inference"
    supporting_evidence: list[EvidenceCitation]

class FiveWhysChain(BaseModel):
    chain_id: UUID
    initial_problem: str
    steps: list[FiveWhysStep]
    terminal_root_cause: str
    confidence: float

class FishboneCause(BaseModel):
    cause: str
    sub_causes: list[str]
    supporting_evidence: list[EvidenceCitation]

class FishboneCategory(BaseModel):
    category: str                        # "Manpower" | "Method" | "Machine" | "Material" | "Measurement" | "Environment"
    causes: list[FishboneCause]

class RankedHypothesis(BaseModel):
    rank: int
    iso14224_failure_mode: str           # KG-validated
    iso14224_mechanism: str              # KG-validated
    iso14224_cause: str | None
    confidence: float
    narrative: str
    supporting_evidence: list[EvidenceCitation]
    contradicting_evidence: list[EvidenceCitation]

class RecommendedAction(BaseModel):
    action: str
    rationale: str
    priority: str                        # "immediate" | "next_shutdown" | "monitor"
    estimated_effort: str | None

class EngineerEdit(BaseModel):
    field_path: str                      # e.g. "primary_hypothesis.narrative"
    before: Any
    after: Any
    edited_at: datetime
    engineer_notes: str | None

class RcaConclusion(BaseModel):
    conclusion_id: UUID
    probe_run_id: UUID
    evidence_package_id: UUID
    canonical_id: str
    primary_hypothesis: RankedHypothesis
    alternative_hypotheses: list[RankedHypothesis]
    fishbone: list[FishboneCategory]
    five_whys: FiveWhysChain
    recommended_actions: list[RecommendedAction]
    engineer_edits: list[EngineerEdit]   # empty if approved as-is
    engineer_approval_status: str        # "approved" | "approved_with_edits" | "rejected"
    engineer_notes: str | None
    validation_errors: list[str]         # non-empty only when validation passed with warnings
    agent_name: str                      # "rca_agent_v1"
    agent_version: str
    generated_at: datetime
    finalized_at: datetime               # set when engineer responds
    schema_version: str = "v1"
```

`EvidenceCitation` shape unchanged: `{section, item_id, relevance}`.

### 5.5 Validation rules

Before proposing the conclusion to the engineer:

1. Every `iso14224_failure_mode` and `iso14224_mechanism` resolves to an existing KG node — else 1 retry of `rank_hypotheses`, then surface as `validation_errors` (don't block; engineer decides)
2. Every `EvidenceCitation.item_id` resolves to a real item in the source Evidence Package — else drop and log
3. `primary_hypothesis.confidence ≥ all alternative_hypotheses[*].confidence`
4. `five_whys.steps` is non-empty and has ≥ 3 steps
5. `fishbone` has at least 3 of 6 categories populated
6. `recommended_actions` is non-empty

Validation failures populate `validation_errors` on the proposed conclusion. The engineer sees them in the conclusion-review HITL turn and can still approve/edit/reject. Hard-block only on KG-validation failure of ISO codes — those would corrupt the KG warm-layer write if persisted.

### 5.6 Persistence

`rca_conclusions` table:

| Column | Type | Notes |
|---|---|---|
| `conclusion_id` | UUID | PK |
| `probe_run_id` | UUID | FK to `probe_runs` |
| `evidence_package_id` | UUID | FK to `evidence_packages` |
| `canonical_id` | TEXT | Indexed |
| `status` | TEXT | `proposed` / `approved` / `approved_with_edits` / `rejected` / `validation_failed` / `budget_exceeded` |
| `agent_name` / `agent_version` | TEXT | |
| `schema_version` | TEXT | default `'v1'` |
| `payload` | JSONB | Full `RcaConclusion` |
| `llm_call_ids` | UUID[] | All LLM calls used during the run |
| `generated_at` | TIMESTAMPTZ | Initial proposal time |
| `finalized_at` | TIMESTAMPTZ | When engineer responded |

Rejected conclusions ARE persisted (with `status='rejected'`) — they're valuable signal for the KG flywheel and future prompt tuning.

### 5.7 Workflow integration

Same leg-loop pattern as planning and gather:

```python
graph_state = None
hitl_input = None
while True:
    leg = await execute_activity(
        run_agent_leg,
        agent_name="rca",
        graph_state=graph_state,
        hitl_response=hitl_input,
        budget=remaining_budget,
        ...
    )
    graph_state = leg.graph_state
    if not leg.needs_hitl:
        break
    self._pending_hitl_turn = leg.hitl_turn
    persist_hitl_turn_to_probe_memory(leg.hitl_turn)
    await wait_condition(lambda: self._hitl_response is not None)
    hitl_input = self._hitl_response
    self._hitl_response = None
conclusion = leg.final_output['conclusion']
```

The conclusion-review HITL uses the SAME `/hitl/respond` endpoint as planning HITL (with `conclusion_edits` populated). No new HITL transport — same Temporal signal mechanism.

### 5.8 Future engine swap

When a partner engine replaces our RCA agent:

- The `run_agent_leg(agent_name="rca", ...)` activity body is replaced with one that calls the remote engine
- The remote engine either honors the same HITL contract (returning `needs_hitl=true` mid-analysis) OR runs to completion in one shot
- The workflow's HITL bridge logic is unchanged
- The `RcaConclusion` contract is unchanged
- KG persistence and follow-up WO logic in WI6 are unchanged

This is enforced by a test that swaps `rca_graph.build_graph()` for a fake one and verifies the workflow still runs to completion.

### 5.9 REST API additions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/probes/runs/{id}/conclusion` | Returns the `RcaConclusion` (404 if not generated; returns latest proposed even before engineer approval) |
| `GET` | `/rca_conclusions/{id}` | Direct lookup |
| `POST` | `/rca_conclusions/{id}/regenerate` | Re-run RCA agent on the same Evidence Package (e.g. after prompt-version bump). Creates a new `conclusion_id`. |

Conclusion-review HITL uses the existing `/probes/runs/{id}/hitl/respond` endpoint.

### 5.10 Acceptance

- RCA agent is a LangGraph agent in `packages/agents/rca_graph.py` using the WI2 leg pattern
- Agent legs participate in the same Temporal workflow loop as planning and gather legs
- For the P-2103A scenario:
  - Fishbone is produced with ≥3 of 6 categories populated and evidence-cited causes
  - 5 Whys chain has ≥3 steps and terminates at a root cause
  - Primary hypothesis cites WO-48291 (coupling replacement) and references mechanical-seal / alignment mechanisms
  - All ISO 14224 codes validate against KG ontology
  - All citations resolve to real Evidence Package items
- Cold-start probe (empty KG, no prior failure events) emits ≥1 evidence-gap HITL turn before 5 Whys begins
- 5 Whys can emit mid-loop HITL turns when an answer requires human knowledge (verified by a test forcing this branch)
- Engineer approval moves probe to close phase (WI6); rejection persists conclusion with `status='rejected'` and ends probe with `status='conclusion_rejected'`
- Engineer edits are applied and recorded in `engineer_edits` list
- Validation failures populate `validation_errors`; conclusion is still surfaced to engineer; only invalid KG ISO codes hard-block
- Replay-from-cache produces byte-identical conclusions for the same Evidence Package + same HITL responses
- Engine-swap test: replacing `rca_graph.build_graph()` with a fake produces a workflow-completable conclusion without other code changes

---

## Work Item 6 — KG Persistence + Follow-up WO Creation

**Goal:** Close the probe loop deterministically after the RCA agent's conclusion-review HITL gate has produced an approved (or approved-with-edits) conclusion. Write the conclusion to the KG warm layer as a `HistoricalFailureEvent` and create a follow-up work order in Maximo. No HITL here — all human decisions already happened in WI5.

### 6.1 Trigger

WI6 runs only when the RCA agent's final leg returned with `engineer_approval_status in {"approved", "approved_with_edits"}`. Rejected conclusions skip WI6 entirely; the workflow finalizes with `status='conclusion_rejected'`.

### 6.2 KG persistence

Activity `persist_conclusion_to_kg` writes:

```cypher
MERGE (fe:HistoricalFailureEvent {id: $event_id})
SET fe.probe_run_id = $probe_run_id,
    fe.conclusion_id = $conclusion_id,
    fe.canonical_id = $canonical_id,
    fe.iso14224_failure_mode = $mode,
    fe.iso14224_mechanism = $mechanism,
    fe.iso14224_cause = $cause,
    fe.narrative = $narrative,
    fe.confidence = $confidence,
    fe.detected_at = $reference_time,
    fe.concluded_at = $finalized_at,
    fe.engineer_approved = true,
    fe.engineer_approval_status = $approval_status

MERGE (a:Asset {id: $canonical_id})-[:HAS_FAILURE_EVENT]->(fe)
MERGE (fm:FailureMode {code: $mode})
MERGE (fe)-[:CLASSIFIED_AS]->(fm)
MERGE (mech:FailureMechanism {code: $mechanism})
MERGE (fe)-[:CAUSED_BY_MECHANISM]->(mech)
```

This is the **first write to the KG warm layer**. Every future probe on the same asset or equipment class will see this event via `kg.get_asset_context` and the planning agent will use it for plan enrichment (per the use case doc §3.1).

Idempotency: `event_id` is deterministic from `conclusion_id`, so re-running the activity does not duplicate events.

### 6.3 Follow-up WO creation

If `recommended_actions` were approved (engineer's HITL response indicated approval of actions, default true if not specified):

- Activity `create_followup_wo` calls Maximo's WO creation tool via a new `work_order.create` MCP tool (additive — see §6.4)
- WO body assembled from `recommended_actions[0]` (primary action) with references to `probe_run_id`, `conclusion_id`, `failure_event_id`
- Idempotency: WO creation keyed on `(probe_run_id, conclusion_id)` — re-running does not duplicate
- Failure handling: WO creation failure does NOT fail the probe — surface in `errors`, mark `wo_creation_status='failed'`, probe still completes with `status='completed'`

### 6.4 New `work_order.create` MCP tool

Additive to the existing `work_order` MCP (no rename of existing tools, keeps the Sprint 2b no-vendor-tool-names invariant):

```python
class CreateWorkOrderRequest(BaseModel):
    canonical_id: str
    description: str
    priority: str           # mapped from RecommendedAction.priority
    work_type: str          # "PM" | "CM" | "INSPECTION"
    references: dict        # {probe_run_id, conclusion_id, failure_event_id}
    requested_by: str       # engineer user id (from HITL response)
```

Returns the created `WorkOrder` entity with vendor_id. The Maximo simulator gets a minimal write capability if it doesn't already support it.

### 6.5 Workflow integration

```python
if rca_conclusion.engineer_approval_status in ("approved", "approved_with_edits"):
    await workflow.execute_activity(persist_conclusion_to_kg, args=[rca_conclusion], ...)
    if rca_conclusion.recommended_actions and hitl_response.actions_approved:
        try:
            wo = await workflow.execute_activity(
                create_followup_wo,
                args=[rca_conclusion],
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            workflow.set_attribute("followup_wo", wo)
        except ActivityError as e:
            workflow.set_attribute("wo_creation_status", "failed")
            workflow.set_attribute("wo_creation_error", str(e))
    await workflow.execute_activity(finalize_probe_run, args=[probe_run_id, "completed"])
else:
    await workflow.execute_activity(finalize_probe_run, args=[probe_run_id, "conclusion_rejected"])
```

### 6.6 REST API additions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/probes/runs/{id}/failure_event` | Returns the persisted `HistoricalFailureEvent` (404 if probe was rejected or still running) |
| `GET` | `/probes/runs/{id}/followup_wo` | Returns the created WO ref (404 if not created) |

### 6.7 Acceptance

- After an approved conclusion, `HistoricalFailureEvent` is written to KG with correct edges (`HAS_FAILURE_EVENT`, `CLASSIFIED_AS`, `CAUSED_BY_MECHANISM`)
- KG write is idempotent: re-running `persist_conclusion_to_kg` produces zero second-write operations (verified by write-count assertion)
- WO creation is idempotent on `(probe_run_id, conclusion_id)` — second run returns the same vendor_id
- WO creation failure surfaces in `errors` and `wo_creation_status` but does NOT fail the probe
- Rejected conclusions skip WI6 entirely; probe finalizes with `status='conclusion_rejected'`
- A two-probe test confirms the flywheel: probe 1 on P-2103A produces an approved conclusion → probe 2 on P-2103A sees the persisted `HistoricalFailureEvent` via `kg.get_asset_context` and the planning agent's prompt includes prior-event context
- Maximo simulator supports the new `work_order.create` tool
- Probe `status='completed'` requires both KG write AND WO attempt (success or surfaced failure) to have run

## End-to-end probe flow (one diagram)

```
HTTP: POST /probes/run {"prompt": "..."}
  ↓
FastAPI: starts Temporal workflow, returns probe_run_id
  ↓
TEMPORAL: ProbeWorkflow on rca-probes queue
  ↓
  ┌── PLANNING PHASE (WI3) ─────────────────────────────────────────────┐
  │   loop:                                                             │
  │     Activity: run_agent_leg(agent="planning", state, hitl_input)    │
  │       └── LangGraph: parse intent → resolve asset → load KG →       │
  │           shortlist → draft plan → maybe ask HITL                   │
  │     if needs_hitl:                                                  │
  │       persist HitlTurn to probe_memory                              │
  │       workflow.wait_condition(hitl_response_received)               │
  │       continue loop                                                 │
  │     else:                                                           │
  │       break with final_plan                                         │
  └─────────────────────────────────────────────────────────────────────┘
  ↓
  ┌── GATHER PHASE (WI4) ────────────────────────────────────────────────┐
  │   loop:                                                              │
  │     Activity: run_agent_leg(agent="gather", state, hitl_input)       │
  │       └── LangGraph: execute plan steps → detect low-conf → maybe    │
  │           ask HITL → materialize KG → anomalies → doc scoring →      │
  │           assemble EvidencePackage                                   │
  │     same HITL pattern as planning                                    │
  │   on completion: EvidencePackage persisted                           │
  └──────────────────────────────────────────────────────────────────────┘
  ↓
  ┌── RCA PHASE (WI5) ───────────────────────────────────────────────────┐
  │   loop:                                                              │
  │     Activity: run_agent_leg(agent="rca", state, hitl_input)          │
  │       └── LangGraph: load evidence → build fishbone →                │
  │           detect gaps (maybe HITL) → 5 whys loop (maybe HITL) →      │
  │           rank hypotheses → validate → propose conclusion (HITL)     │
  │     same HITL pattern as planning and gather                         │
  │   on completion: RcaConclusion persisted with approval status        │
  └──────────────────────────────────────────────────────────────────────┘
  ↓
  ┌── CLOSE PHASE (WI6) ─────────────────────────────────────────────────┐
  │   if engineer_approval_status in {approved, approved_with_edits}:    │
  │     Activity: persist_conclusion_to_kg (HistoricalFailureEvent)      │
  │     Activity: create_followup_wo (if actions approved)               │
  │   Activity: finalize_probe_run(status=completed|conclusion_rejected) │
  └──────────────────────────────────────────────────────────────────────┘
  ↓
TEMPORAL workflow completes
HTTP: GET /probes/runs/{id}/conclusion → returns RcaConclusion
```

---

## Cross-cutting acceptance

Sprint 3 is complete when ALL of the following hold simultaneously:

1. `POST /probes/run` accepts a free-text prompt and starts an end-to-end probe workflow
2. The workflow spans planning, gather, RCA analysis (with conclusion-review HITL inside the agent), KG persistence, and follow-up WO — one workflow per probe, end to end
3. `packages/llm/` provides the single non-bypassable LLM client; every call audited in `llm_calls`
4. `packages/agents/` provides the leg-pattern foundation; planning, gather, and RCA agents all use it
5. Probe memory persists in three layers (Temporal event history, Postgres snapshot, LangGraph in-memory)
6. HITL is bidirectional: agents ask clarifying questions, engineers approve plans and conclusions, edits flow back into agent state
7. HITL questions are batched per turn (no single-question turns when other questions are pending)
8. Lazy KG Asset materialization works (first-touch population on first probe)
9. `EvidencePackage` is structured, persisted, retrievable; LLM-derived fields carry `method` provenance
10. RCA agent (LangGraph, third agent in the workflow) produces a valid `RcaConclusion` with fishbone + 5 Whys + ranked hypotheses, with HITL for evidence gaps, 5 Whys human-knowledge questions, and conclusion review
11. All ISO 14224 codes in conclusions validate against the KG ontology
12. Engineer-approved conclusions persist to KG as `HistoricalFailureEvent` (first warm-KG writes)
13. Follow-up WOs are created in Maximo when recommended actions are approved
14. A second probe on the same asset sees the persisted failure event via `kg.get_asset_context`
15. `replay_from_cache=True` + explicit `reference_time` produces byte-identical probes (excluding generation timestamps)
16. Partial coverage works: unhealthy connection mid-gather → category skipped, probe still completes
17. Negative-trigger invariant: nothing auto-starts probes — prompt entry only in Phase 1
18. `task test` is green; hermetic tests use replay-from-cache exclusively
19. Zero new code touches: external RAG corpora, fine-tuning, evaluation harness, alarm-bridge auto-trigger, multi-asset probes (Phase 2)

---

## Out of scope (Phase 2 or later)

- Alarm-bridge / event-driven probe triggers (the workflow accepts prompt-shaped inputs from any source; the bridge isn't built)
- External RCA engine as a separate service (Sprint 3 ships the in-process stub; remote engine is a transport swap behind the same activity)
- RAG over external OEM bulletins / ISO docs / industry papers
- Fine-tuned models for any stage
- Evaluation harness with golden-set labeled conclusions
- Multi-asset probes (failure patterns across a unit)
- Cross-probe pattern detection (fleet-wide flywheel beyond `HistoricalFailureEvent` lookup)
- User feedback loop beyond accept/edit/reject (thumbs up/down, comments, training data export)
- Cost dashboards / per-tenant LLM billing
- Resolution Queue UX (write paths already in 2b; UX is Phase 2)
- PDF rendering of Evidence Packages or RCA Conclusions
- Engineer-driven probe pause / cancel mid-flight (clean shutdown of in-flight workflow)

---

## Risk callouts

1. **LangGraph + Temporal integration is new in our codebase.** First implementation. Mitigation: WI2 ships the foundation in isolation with its own tests before WI3/WI4 build on it. If serialization issues bite, escape hatch in 2.5 is ready.
2. **HITL UX is unbuilt; we're shipping API only.** Engineers interact via curl/Postman in Sprint 3. Real UX comes later. Document this in the README.
3. **Cold-start HITL fatigue.** First probe on a plant has lots of questions because KG is empty. Batching helps; aggressive prompting that minimizes questions helps more. Watch this in early testing.
4. **Token budget can be tight across many HITL legs.** Each leg replays graph state into the LLM. Budget accounting is cumulative across legs. If we exceed budget mid-probe, the workflow emits a HITL turn asking permission to extend budget OR ends with partial result.
5. **KG warm-layer schema is being defined as we ship.** `HistoricalFailureEvent` shape is set in WI6; future probes depend on it. Get the shape right before WI6 lands or migrations get painful.
6. **The RCA agent in our codebase is a placeholder for a future methodology-rich engine.** A prompt-driven LangGraph agent producing fishbone + 5 Whys is not the same depth as a partner tool like Pinnacle's. Acceptance criteria validate the contract, the agent seam, and end-to-end flow — not analytical depth. Engine-swap test in WI5 protects the seam.
7. **Maximo WO creation requires a write-capable Maximo connection.** Verify the connector simulator supports WO writes; if not, simulator gets a minor enhancement in WI6.
8. **`reference_time` propagation across many activities and LLM calls.** Bug here breaks determinism. Hermetic test asserts every activity and every LLM call's variables carry the workflow-frozen reference_time, not `now()`.
9. **Probe memory growth at real-plant scale.** Refplant is fine; at 100s of probes/day with long HITL conversations, `probe_memory.payload` rows grow. The 1-month archival job is necessary, not nice-to-have.
10. **Multi-agent state passing assumes LangGraph state serializes cleanly.** Some LangChain message types serialize awkwardly. WI2 includes round-trip serialization tests on representative shapes (tool calls, messages with attachments, partial state).

---

## Gaps to verify and resolve (Claude Code: read this section first)

The following items were flagged in a spec review against `rca_use_case_adil.md`, `sprint1_spec.md`, `sprint2a_spec.md`, `sprint2b_spec.md`, and `rca_platform_consolidated_context.md`. **For each item: confirm against the actual code/spec state, decide whether it is a real gap, and if real, fix it in code + this spec in the same change. If it is not a real gap (already covered, intentionally out of scope, or superseded), leave a one-line note in the PR description explaining why.** Do not assume the reviewer's read is correct — verify first.

### Must-verify (likely real gaps)

1. **Tool-count invariant drift.** Sprint 2b acceptance says "six entity MCP servers, no vendor-prefixed tools." This spec adds `kg.upsert_asset`, `kg.link_failure_mode`, `kg.get_asset_context` (§4.2) and `work_order.create` (§6.4). Confirm the actual count in the codebase, then update §2.8 acceptance to match (and confirm none of the new tools violate the no-vendor-prefix invariant).

2. **`kg.get_asset_context` request/response shape is unspecified.** Referenced in §4.1, §4.2, §6.7, and the end-to-end diagram, but no schema. Define the shape inline in §4.2 (input: canonical_id + optional class fallback; output: AssetSummary + applicable FailureModes + prior `HistoricalFailureEvent`s on this asset + class-level prior events at this plant) — or confirm it already exists somewhere in the codebase and reference it.

3. **`kg.upsert_asset` and `kg.link_failure_mode` request/response shapes are unspecified.** Same problem as #2. Define inline. `kg.link_failure_mode` MUST validate `(EquipmentClass)-[:CAN_EXHIBIT]->(FailureMode)` against the Sprint 2a ontology before writing.

4. **Canonical_id regex enforcement on new KG `Asset` nodes.** Sprint 1 invariant: `^asset:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$`. Sprint 3 §4.2 creates KG Asset nodes via `kg.upsert_asset` — verify the regex is enforced on the `Asset.id` property and add an acceptance line in §4.6.

5. **`provenance.connection_id` preservation.** Sprint 2b §3.5 requires every entity MCP response to carry `provenance.connection_id`. Sprint 3 references `ProvenanceEntry` in `EvidencePackage` (§4.3) but does not define it. Confirm the existing `ProvenanceEntry` shape in code carries `connection_id`; if not, extend it. Inline the shape in §4.3.

6. **Resolution threshold for gather-phase ambiguity.** §4.1 node 2 says "low-confidence resolutions trigger HITL" but does not name the threshold. Confirm whether the existing `MAR_AUTO_ACCEPT_THRESHOLD` (0.92, Sprint 1 §2.5) is reused for tag/doc resolution during gather, or whether a separate `GATHER_AUTO_ACCEPT_THRESHOLD` is needed. Pin the answer in §4.1.

### Should-verify (consistency with use case doc)

7. **`RecommendedAction` missing fields from use case.** `rca_use_case_adil.md` §4.2 shows `recommended_actions[*].preconditions` (list, e.g. "increase_vib_monitoring_frequency_to_daily") and `target` (e.g. "NDE_bearing"). Spec §5.4 omits both. Verify whether they're needed for the WO creation in §6.3 — if yes, add to `RecommendedAction`.

8. **`open_data_requests` missing from `RcaConclusion`.** Use case §4.2 includes this as a separate output from `recommended_actions` (e.g. "pull lube oil sample — last one 90 days old"). Decide whether it folds into `recommended_actions` with a `priority='monitor'` or warrants its own field on `RcaConclusion`. Document the decision.

9. **Alarm-bridge trigger vs prompt-only entry.** Use case §2.1 describes an alarm-stream trigger; spec §spec-decisions and acceptance #17 enforce prompt-only entry with no auto-trigger. This is intentional (Phase 2), but confirm there is one explicit sentence in §spec-decisions calling out the deferral so the use-case-doc reader is not surprised.

10. **`reference_time` origin is undefined.** Risk #8 requires reference_time to propagate, but no work item states where it is set. Confirm it lives in the `POST /probes/run` body (defaulting to workflow start if omitted) and document the request schema. Acceptance test should assert every activity input and every `LLMClient.complete` call carries the workflow-frozen reference_time.

11. **`POST /probes/run` request body is undefined.** Define it: `{prompt: str, plant_id: str | None, reference_time: datetime | None, requested_by: str}`. Confirm whether `plant_id` is required or inferred from prompt/context.

12. **Temporal task queue name for probes.** Sprint 2b uses `rca-onboarding`. This spec needs a new queue. Confirm `rca-probes` (or whatever was decided) is stated in WI2 infra and used by the worker config.

13. **Engineer identity on HITL responses.** §6.4 `CreateWorkOrderRequest.requested_by` is sourced "from HITL response," but `HitlResponse` (§3.6) has no `responded_by` field. Add it, or confirm it is captured elsewhere (e.g. an auth header on `POST /hitl/respond`).

14. **Plan-step → MCP-tool mapping is implicit.** §4.1 says the gather agent calls "the appropriate MCP tools" but doesn't enumerate `step_type → tool` mappings. Pin them: `tag_history→tag.get_history`, `work_orders→work_order.list_for_asset`, `documents→document.search_for_asset`, `operator_logs→operator_log.list_for_asset`, `kg_query→kg.*`. Confirm these tool names match what Sprint 2b actually shipped.

15. **Resolution Queue interaction during gather.** Sprint 2b shipped `/resolution_queue` write paths. Decide whether the gather agent writes `pending_review` entries when it hits ambiguous bindings, or surfaces them only via in-probe HITL. State the decision in §4.5.

16. **`evidence_packages` table schema is referenced but not inlined.** §4.4 says "same shape as prior draft" but the prior draft (3a/3b) was deleted. Inline the column list: `evidence_package_id` PK, `probe_run_id` FK, `canonical_id` indexed, `investigated_failure_modes` TEXT[], `schema_version` TEXT, `payload` JSONB, `assembled_at` TIMESTAMPTZ. Or confirm an existing migration covers it.

17. **`probe_runs` table is referenced everywhere but never defined.** `probe_memory.probe_run_id REFERENCES probe_runs(probe_run_id)` (§2.4), `evidence_packages.probe_run_id` (§4.4), all REST endpoints. Define the table: `probe_run_id` PK, `workflow_id`, `plant_id`, `prompt`, `reference_time`, `status`, `started_at`, `completed_at`, `requested_by`, `final_canonical_id`, `errors` JSONB. Mirrors Sprint 2b `onboarding_runs`.

18. **`probe_runs.status` enum is fragmented across the spec.** Mentions: `planning_aborted` (§3.4), `conclusion_rejected` (§5.10, §6.1), `completed` (§6.5), `budget_exceeded` (§1.5 — confirm this is also a probe-level status, not just a coverage field). Enumerate the full set in one place when defining the `probe_runs` table.

### Nice-to-verify

19. **Driving-scenario fixture reuse.** Acceptance tests use P-2103A. Confirm the Sprint 1 refplant seed already covers this asset end-to-end (MAR + KG hierarchy + connection bindings for all 4 categories). If anything is missing for the Sprint 3 scenario to run hermetically, add seed data — but do not duplicate.

20. **HITL signal-flow clarity.** Risk #1 and §3.5 cover this in prose. Consider adding a small diagram (or pseudo-sequence) for `POST /hitl/respond → workflow.signal() → wait_condition releases` — this is the single most likely place for Claude Code to drift on the Temporal+LangGraph seam.

21. **`HistoricalFailureEvent` → WO edge.** Use case §4.3 says the failure event node should also connect to the work order created as a result. Spec §6.2 Cypher only writes `CLASSIFIED_AS` and `CAUSED_BY_MECHANISM`. Add `(fe)-[:RESULTED_IN]->(:WorkOrder {id: $wo_id})` after WI6's WO creation succeeds, or document why it is deferred.

22. **Explicit "out of scope" coverage.** Use case §6 mentions PFMEA scoring and hypothesis-rank calibration against historical ground truth. Confirm these are in the Phase 2 list, or add them to §out-of-scope.

### Resolution protocol

For each item above:

- **Real gap, in scope:** fix in code + amend this spec in the same commit; cite the verifying check.
- **Real gap, out of scope:** add a one-liner to §out-of-scope and explain the deferral.
- **Not a gap (already covered):** leave a short note in the PR description with the file/line that already covers it. No spec change.

Do not silently skip any item.

---

## Gap Resolutions (resolved during Sprint 3 execution — 2026-06-11)

Every item above was verified against the actual Sprint-2b codebase. This section is the **authoritative contract reference**: where the spec body and this section disagree, this section wins. Each resolution cites the verifying check.

### G1 — Tool-count invariant drift → REAL GAP (off-by-one), fixed

**Verified:** the entity-MCP surface ships **19** tools, not 20 (`scripts/run_mcp_host.py` mounts six servers; counted via `@mcp.tool` decorators):
`asset.*` (3: resolve, get, search), `kg.*` (4: get_ontology_node, list_failure_modes_for_class, get_hierarchy, find_path), `tag.*` (4: list_for_asset, get_history, get_current, get_metadata), `operator_log.*` (2: list_for_asset, get), `work_order.*` (3: list_for_asset, get, list_recent), `document.*` (3: search_for_asset, get, list_by_type).

Sprint 3 adds **4**: `kg.upsert_asset`, `kg.link_failure_mode`, `kg.get_asset_context`, `work_order.create` → **post-sprint total 23**. None use a forbidden vendor prefix (`packages/cross_source_tests/test_no_vendor_tool_names.py` forbids only `pi.|maximo.|documents.|assets.`; `kg.` and `work_order.` are entity vocabulary). §2.8 acceptance corrected to "19".

### G2 — `kg.get_asset_context` shape → REAL GAP, defined

```python
class GetAssetContextRequest(BaseModel):
    canonical_id: str
    iso14224_class: str | None = None      # fallback class if the Asset node isn't materialized yet

class AssetContext(BaseModel):
    kg_warm: bool                          # True if ≥1 prior HistoricalFailureEvent exists (asset or class)
    asset: AssetContextSummary | None      # None on a cold KG (asset not yet materialized)
    iso14224_class: str | None
    applicable_failure_modes: list[FailureModeEntry]      # from (EquipmentClass)-[:CAN_EXHIBIT]->(FailureMode)
    prior_events_on_asset: list[FailureEventSummary]      # (Asset)-[:HAS_FAILURE_EVENT]->(HistoricalFailureEvent)
    prior_events_for_class_at_plant: list[FailureEventSummary]  # same class, same plant, other assets
```
`FailureEventSummary = {event_id, canonical_id, iso14224_failure_mode, iso14224_mechanism, narrative, confidence, concluded_at}`. Returns `ToolResponse[AssetContext]`. Read-only (no writes); class-level lookup keys on `Asset.iso14224_class` + `Asset.plant_id`.

### G3 — `kg.upsert_asset` / `kg.link_failure_mode` shapes → REAL GAP, defined

```python
class UpsertAssetRequest(BaseModel):
    canonical_id: str                      # MUST match ^asset:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$ (see G4)
    name: str
    iso14224_class: str                    # ontology EquipmentClass id (e.g. "bb1")
    iso14224_class_confidence: float
    iso14224_class_method: str             # "register" | "rule:<id>" | "llm_v1"
# plant_id + unit_slug are DERIVED from canonical_id via parse_canonical_id (not passed)

class LinkFailureModeRequest(BaseModel):
    canonical_id: str
    failure_mode_code: str                 # ISO code, e.g. "ELP"; validated against ontology before write
```
`kg.upsert_asset` MERGEs the `Asset {id: canonical_id}` node, sets properties + `materialized_at`/`last_probed_at` (via `workflow.now()`-frozen `reference_time`, passed in), and MERGEs `(Asset)-[:LOCATED_IN]->(Unit {id: "unit:{plant}:{unit_slug}"})` and `(Asset)-[:INSTANCE_OF]->(EquipmentClass {id: iso14224_class})`. Idempotent (re-run = zero new writes, verified by a write-count assertion mirroring `InMemoryHierarchyWriter`). `kg.link_failure_mode` **first validates** `(EquipmentClass {id})-[:CAN_EXHIBIT]->(FailureMode {code})` exists in the Sprint-2a ontology; if not, returns `ToolError(code="validation_failed")` and writes nothing; on success MERGEs `(Asset)-[:CAN_EXHIBIT]->(FailureMode)`. Both return `ToolResponse`. The `FailureMode` is matched by **`code`** (indexed `failure_mode_code`), never minted, so it binds to the existing ontology node (its uniqueness constraint is on `id`).

### G4 — canonical_id regex on KG `Asset.id` → enforcement added

The regex `^asset:([a-z0-9-]+):([a-z0-9-]+):([a-z0-9-]+)$` lives in `packages/contracts/src/rca_contracts/canonical.py:13` (`parse_canonical_id`). `kg.upsert_asset` calls `parse_canonical_id(canonical_id)` and rejects a malformed id with `ToolError(code="validation_failed")` **before** any write. §4.6 acceptance gains: "kg.upsert_asset rejects a canonical_id that fails the Sprint-1 regex."

### G5 — `ProvenanceEntry` shape → REAL GAP, defined (reuses existing `Provenance`)

The existing `Provenance` model (`packages/contracts/src/rca_contracts/provenance.py:11`) already carries `connection_id`, `queried_at`, `response_id`, `record_count`, etc. The Evidence Package needs a *cross-section index* into provenance, so we add a thin `ProvenanceEntry`:
```python
class ProvenanceEntry(BaseModel):
    section: str          # "tag" | "work_order" | "document" | "operator_log" | "kg" | "asset"
    item_id: str          # the id of the cited item within that section
    connection_id: str | None
    tool_name: str
    queried_at: datetime
    response_id: UUID
    record_count: int
```
Each gather tool call yields one `ProvenanceEntry` per section touched, populated from the `Provenance` on the tool response. `EvidencePackage.provenance: list[ProvenanceEntry]`. **Acceptance:** every `ProvenanceEntry` from a connector-backed section carries a non-null `connection_id`.

### G6 — gather-phase resolution threshold → separate `GATHER_AUTO_ACCEPT_THRESHOLD`

`MAR_AUTO_ACCEPT_THRESHOLD` (0.92, `packages/mar/src/rca_mar/config.py:9`) gates **asset-identity** resolution and is reused for that. Gather-phase **tag/document** binding is lower-stakes (asset identity already settled in planning) and uses a dedicated `GATHER_AUTO_ACCEPT_THRESHOLD` (env-overridable, **default 0.85**, mirroring the crosswalk confidence `_CROSSWALK_CONFIDENCE = 0.85`). Below it → HITL. Pinned in §4.1 node 2. Lives in a new `rca_agents.config.gather_auto_accept_threshold()`.

### G7 — `RecommendedAction.preconditions` / `.target` → added

```python
class RecommendedAction(BaseModel):
    action: str
    rationale: str
    priority: str                 # "immediate" | "next_shutdown" | "monitor"
    estimated_effort: str | None = None
    target: str | None = None             # e.g. "NDE_bearing", "mechanical_seal" (use case §4.2)
    preconditions: list[str] = []         # e.g. ["increase_vib_monitoring_frequency_to_daily"]
```
`target` and `preconditions` flow into the follow-up WO description assembled in §6.3.

### G8 — `open_data_requests` → its own field on `RcaConclusion`

Data-gathering asks ("pull lube-oil sample — last one 90 days old") are **not** maintenance actions, so they get their own field rather than overloading `recommended_actions` with `priority='monitor'`:
```python
class OpenDataRequest(BaseModel):
    request: str
    rationale: str
    target: str | None = None
# RcaConclusion gains:  open_data_requests: list[OpenDataRequest] = []
```
They do **not** trigger a follow-up WO (WI6 only acts on `recommended_actions`).

### G9 — alarm-bridge deferral → explicit sentence added

Added to "Architectural decisions": *"Alarm-stream / event-driven probe triggers (use case §2.1) are explicitly deferred to Phase 2. The workflow accepts prompt-shaped input from any source; in Sprint 3 the only source is `POST /probes/run`. No component subscribes to alarms or auto-starts probes (cross-cutting acceptance #17)."*

### G10 + G11 — `reference_time` origin and `POST /probes/run` body → defined

```python
class StartProbeRequest(BaseModel):
    prompt: str
    plant_id: str | None = None           # omitted → inferred during planning; defaults to the single
                                          #   configured refplant (refinery-gc) at refplant scale
    reference_time: datetime | None = None # omitted → frozen to workflow start (workflow.now())
    requested_by: str                      # engineer user id (email)
```
`reference_time` is frozen **once** at workflow start (`self._reference_time = inp.reference_time or workflow.now()`) and threaded into **every** activity input and **every** `LLMClient.complete(..., variables={..., "reference_time": ...})` call. Determinism test (risk #8) asserts no activity or LLM call observes wall-clock `now()`. `POST /probes/run` returns `202 {"workflow_id": ..., "probe_run_id": ...}` (probe_run_id minted by the workflow via `workflow.uuid4()` and written to `probe_runs`, mirroring onboarding's deferred-id pattern).

### G12 — Temporal task queue → `rca-probes`

Confirmed distinct from onboarding's `rca-onboarding`. `rca_agents.worker.TASK_QUEUE = "rca-probes"` (env `PROBE_TASK_QUEUE`). A new `task probe:worker` and `task api:probes` are added to the Taskfile.

### G13 — engineer identity on `HitlResponse` → `responded_by` added

`HitlResponse` (§3.6) gains `responded_by: str` (engineer email). `CreateWorkOrderRequest.requested_by` (§6.4) is sourced from the conclusion-review `HitlResponse.responded_by`.

### G14 — plan-step → MCP-tool mapping → pinned (names verified to exist)

| `PlanStep.step_type` | MCP tool |
|---|---|
| `tag_history` | `tag.get_history` (also `tag.list_for_asset` to enumerate) |
| `work_orders` | `work_order.list_for_asset` |
| `documents` | `document.search_for_asset` |
| `operator_logs` | `operator_log.list_for_asset` |
| `kg_query` | `kg.get_asset_context` / `kg.list_failure_modes_for_class` |

All five tool names verified present in the Sprint-2b code. Lives as `rca_agents.tools.STEP_TYPE_TO_TOOL`.

### G15 — Resolution Queue during gather → in-probe HITL only

**Decision:** the gather agent surfaces ambiguous tag/document bindings **only via in-probe HITL**, not by writing `pending_review` rows to the global `/resolution_queue`. Rationale: the resolution queue curates **onboarding** asset-alias bindings; probe-time tag/doc relevance is ephemeral and probe-scoped. Stated in §4.5. (A future sprint may promote confirmed probe-time corrections into the queue.)

### G16 — `evidence_packages` table → inlined (alembic `0005`)

`evidence_package_id` UUID PK · `probe_run_id` UUID FK→`probe_runs` (indexed) · `canonical_id` TEXT indexed · `investigated_failure_modes` JSONB (list[str]) · `schema_version` TEXT default `'v1'` · `payload` JSONB (full `EvidencePackage`) · `assembled_at` TIMESTAMPTZ.

### G17 — `probe_runs` table → defined (mirrors `onboarding_runs`, alembic `0005`)

`probe_run_id` UUID PK · `workflow_id` TEXT · `plant_id` TEXT indexed · `prompt` TEXT · `reference_time` TIMESTAMPTZ · `requested_by` TEXT · `status` TEXT · `phase` TEXT · `final_canonical_id` TEXT NULL · `token_usage` JSONB · `errors` JSONB · `started_at` TIMESTAMPTZ · `completed_at` TIMESTAMPTZ NULL. Composite index `(plant_id, status)`. Repo `ProbeRunsRepo` (Protocol + Postgres + InMemory) mirrors `OnboardingRunsRepo`.

### G18 — `probe_runs.status` enum → enumerated in one place

`running` → `planning` → `planning_aborted` (terminal) · `gathering` · `analyzing` · `awaiting_review` · `completed` (terminal) · `conclusion_rejected` (terminal) · `budget_exceeded` (terminal — yes, it is also a probe-level status, set when `TokenBudgetExceeded` ends the probe with a partial result; the coverage field `coverage.llm_status='budget_exceeded'` is the per-package flag) · `failed` (terminal — unhandled activity error).

### G19 — driving-scenario fixture → REAL GAP; rebased P-2103A → **P-101A**

**Verified:** there is no `P-2103A` asset and no `WO-48291` anywhere in the seed or simulator fixtures. The fictional asset comes from the (absent) `rca_use_case_adil.md`. The richest fully-fixtured asset is **P-101A** (`asset:refinery-gc:unit-101:p-101a`), covered end-to-end across all four categories:
- MAR register (`packages/mar/seed_data/refplant_assets.yaml`: P-101A, maximo `CRDU-P101A`, pi_af, uns, sap_pm) + KG hierarchy (`unit:refinery-gc:unit-101`),
- PI signals (vibration_radial, bearing_temp_de, seal_flush_flow, discharge/suction pressure, motor_amps),
- Maximo WOs (`WO-49900001` PM; scenario-driven `WO-50012345` "inspect seal", `WO-50012402` "mechanical seal leak confirmed", failure_code in fixture),
- documents (P-101A datasheet, UNIT-101 P&ID, RCA reports),
- and a ready scenario `rca_simulator/fixtures/refplant/scenarios/seal_leak_progression.yaml` (30-day mechanical-seal degradation; expected_rca: mechanical_seal_failure, root causes dry_running_seal_face + insufficient_flush_flow).

**All acceptance criteria are rebased** to P-101A. The driving prompt becomes `"P-101A discharge pressure has been dropping and vibration is climbing"`. The primary hypothesis cites **WO-50012402** (mechanical seal leak) and references **mechanical-seal / seal-failure** mechanisms. **No seed duplication** (gap item's "do not duplicate" honored).

**ISO-code sub-resolution (linked memory: ISO 14224 seal-leak code conflict):** the scenario fixture tags the failure mode `LEK`, but `LEK` is **not** in the Sprint-2a BB1 ontology (its 19 codes are BRD, ERO, HIO, LOO, VIB, LBP, LCP, STD, OHE, ELP, ELU, FOF, INL, NOI, OTH, PDE, PLU, SER, UNK). Because §5.5 rule 1 **hard-blocks** on ISO codes that don't resolve to KG nodes, the RCA conclusion's `iso14224_failure_mode` for the seal-leak scenario must be **`ELP`** (external leakage – process medium, present in the ontology) and the mechanism **`seal-failure`** (present in the 41-mechanism set). The conclusion narrative may still say "mechanical seal leak"; only the *coded* fields must be ontology-valid.

### G20 — HITL signal-flow → pseudo-sequence added

```
Engineer            FastAPI (api:probes)         Temporal (ProbeWorkflow)        Postgres
   │  POST /probes/runs/{id}/hitl/respond  (HitlResponse)                          │
   │ ───────────────────────────────────▶ │                                       │
   │                                       │ handle = client.get_workflow_handle(workflow_id)
   │                                       │ await handle.signal(                  │
   │                                       │     ProbeWorkflow.hitl_response, body) │
   │                                       │ ◀── 202 accepted                      │
   │                                       │            signal sets self._hitl_response = body
   │                                       │            wait_condition(lambda: self._hitl_response is not None) releases
   │                                       │            next run_agent_leg(hitl_response=body) activity runs
   │  GET /probes/runs/{id}/hitl/pending   │                                       │
   │ ───────────────────────────────────▶ │ ── reads probe_memory.conversation ──▶│
   │  ◀── current HitlTurn (or 204) ───────│                                       │
```
LangGraph never signals Temporal; only the FastAPI handler does (decision #4). The signal name is `hitl_response`; the same endpoint serves planning, gather, and conclusion-review turns (distinguished by `turn_id`).

### G21 — `HistoricalFailureEvent`-[:RESULTED_IN]->`WorkOrder` edge → added to WI6

After `create_followup_wo` succeeds, WI6 writes `MERGE (wo:WorkOrder {id: $wo_vendor_id}) MERGE (fe)-[:RESULTED_IN]->(wo)`. `WorkOrder` is a **new KG node label** (added to migration `0004_asset_layer.cypher` with a uniqueness constraint on `id`). If WO creation fails (non-fatal, §6.3), the edge is simply not written.

### G22 — PFMEA scoring + rank calibration → confirmed Phase 2

Added to §out-of-scope: *"PFMEA criticality scoring (use case §6)"* and *"hypothesis-rank calibration against historical ground-truth (use case §6)."* Sprint 3 ranks hypotheses by the agent's own confidence only.

### G23 (beyond the 22) — `§6.2` persistence Cypher would duplicate ontology nodes → fixed

The spec-body §6.2 Cypher does `MERGE (fm:FailureMode {code: $mode})` and `MERGE (mech:FailureMechanism {code: $mechanism})`. The Sprint-2a ontology constrains uniqueness on **`id`**, not `code`, and `FailureMechanism` nodes are keyed by slug `id` (e.g. `seal-failure`) — a `code`-keyed MERGE would create **duplicate** ontology nodes. **Fix:** §5.5 validation guarantees the codes exist first, then §6.2 uses **`MATCH`** on the existing ontology nodes (`FailureMode` by `code`, `FailureMechanism` by `id`) and only `MERGE`s the new `HistoricalFailureEvent` and its edges:
```cypher
MERGE (fe:HistoricalFailureEvent {id: $event_id}) SET fe += $props
MERGE (a:Asset {id: $canonical_id})
MERGE (a)-[:HAS_FAILURE_EVENT]->(fe)
WITH fe
MATCH (fm:FailureMode {code: $mode})            // ontology node — MATCH, never MERGE
MERGE (fe)-[:CLASSIFIED_AS]->(fm)
WITH fe
MATCH (mech:FailureMechanism {id: $mechanism_id})  // ontology node — MATCH, never MERGE
MERGE (fe)-[:CAUSED_BY_MECHANISM]->(mech)
```
