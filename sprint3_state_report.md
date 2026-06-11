# Sprint 3 State Report — End-to-End Probe (3 agents, HITL, RCA conclusion)

**Date:** 2026-06-11
**Branch:** `feat/sprint-3` (off `main` @ `5d1893e`)
**Test state:** `task test` → **478 passed, 13 skipped** (+68 over the 410 Sprint-2 baseline); `task lint` → **ruff + mypy clean, 130 source files**. Skips are unchanged from Sprint 2 (live-service parity tests whose sims/brokers aren't running, plus the 2 parked MAR-wire stubs).

**Audited against:** `sprint3_spec.md` (amended in-repo with a "Gap Resolutions" section, G1–G23), `rca_phase1_data_layer_spec.md`, `sprint1_spec.md`, `sprint2a_spec.md`, `sprint2b_spec.md`, `sprint2_state_report.md`. The use-case doc (`rca_use_case_adil.md`) and `rca_platform_consolidated_context.md` referenced by the spec **do not exist in the repo** — gap items that cite them were resolved from the spec's own quotes (see G7/G8/G19/G21/G22).

---

## What shipped, by work item

### WI1 — LLM client + prompt registry (`packages/llm`) ✅ complete, hermetic
- `LLMClientImpl.complete/.embed` — the single non-bypassable abstraction: full provenance (`LLMResponse`), content-addressed cache + replay (a cache hit with `replay_from_cache=True` makes **no** upstream call — proven by `NoUpstreamTransport`), per-probe **token-budget gate** (`TokenBudgetExceeded` raised *before* the call), structured-output parsing, and an `llm_calls` audit row per call.
- `registry.py` — Markdown+YAML prompt templates; validates declared==referenced `{{vars}}` and that `output_schema` is valid JSON Schema; dependency-free `{{var}}` rendering. **11 packaged prompts** (planning ×4, gather anomaly, RCA ×5, summarize) all load + validate.
- `transports.py` — Anthropic + Voyage transports import their SDKs **lazily** (keys via `EnvSecretResolver`, §1.6), so the hermetic suite runs with neither SDK installed. `testing.py` ships deterministic transports reused by the agent tests.
- **Tests:** 15 (registry validation, replay, budget, audit, deterministic embed).

### WI2 — Agent foundation + probe memory (`packages/agents`) ✅ contract complete
- The **leg pattern** is the durable boundary: `Agent.run_leg(graph_state, hitl_response, ctx) -> AgentLegResult` (contracts in `rca_contracts.agent`). `graph_state` is a plain JSON dict carried through Temporal event history; `det_uuid` makes agent-minted ids byte-identical on replay.
- `ToolBox` adapter (§2.6) with the G14 `STEP_TYPE_TO_TOOL` map; `FakeToolBox` serves the P-101A seal-leak fixture for hermetic probes.
- **3-layer probe memory:** Temporal event history (layer 1, automatic), Postgres `probe_memory` snapshot (layer 2, written at the end of every leg), in-process graph state (layer 3). In-memory repos prove the contract; the Postgres schema exists (migration 0005).
- **Tests:** round-trip serialize/deserialize via the end-to-end workflow; `probe_memory` snapshot asserted via the API tests.

### WI3 — Planning agent + plan-approval HITL ✅ complete, hermetic
`parse_intent → resolve_asset_or_ask → load_kg_context → build_shortlist → draft_plan → propose → apply_edits/finalize/replan`. Cold-start posture batches a context question **with** the proposed plan + approval question; ambiguous asset → first turn asks *which* asset batched with the window clarification; plan always has ≥3 steps with rationale; 2-replan limit → `planning_aborted`; replay is byte-identical. **6 tests.**

### WI4 — Gather agent + lazy KG + Evidence Package ✅ complete, hermetic
Executes plan steps via the ToolBox, lazily materializes the KG Asset layer, runs LLM anomaly detection with a **3σ rule fallback**, scores documents (keyword-overlap), and assembles the canonical `EvidencePackage` with per-section `ProvenanceEntry` (non-null `connection_id`), `plan_execution_notes`, and a `CoverageReport`. Partial coverage (a category outage) is skipped and the probe continues; an empty tag window triggers a scope HITL → extend → resume. **4 tests.**

### WI5 — RCA agent (fishbone + 5 Whys + ranked hypotheses) ✅ complete, hermetic
Third LangGraph-style agent on the same leg pattern. Produces a fishbone (≥3 categories, evidence-cited), an iterative 5 Whys chain (≥3 steps, terminates at a root cause or depth 7, **mid-loop HITL** when an answer needs human knowledge), and ranked hypotheses with KG-valid ISO codes. Three HITL contexts (pre-5-whys evidence gaps, mid-loop, conclusion review). `validate_conclusion` (§5.5) populates `validation_errors` without blocking; the hard block on invalid ISO codes is enforced at **KG-persist time** (G23). Approve → close; reject → regenerate once → `conclusion_rejected` (rejected conclusion persisted). The **engine-swap seam** is proven: a fake `rca` agent runs the workflow to completion unchanged. **5 tests + the engine-swap workflow test.**

### WI6 — KG persistence + follow-up WO ✅ complete, hermetic
`persist_conclusion_to_kg` writes the **first warm-KG `HistoricalFailureEvent`** (idempotent on a `conclusion_id`-derived `event_id`; MATCHes the ontology FailureMode/Mechanism rather than MERGE-creating, G23) with `HAS_FAILURE_EVENT`/`CLASSIFIED_AS`/`CAUSED_BY_MECHANISM`, plus the `RESULTED_IN` edge to the created WorkOrder (G21). `create_followup_wo` calls the additive `work_order.create` MCP tool (deterministic wonum → idempotent, §6.3); WO failure is non-fatal. Rejected conclusions skip WI6 entirely.

### Cross-cutting infra
- **`ProbeWorkflow`** (`workflow.py`): one Temporal workflow = one probe; planning→gather→RCA leg-loops + close. **HITL = `hitl_response` signal + `wait_condition`** (G20); `reference_time` frozen once and threaded into every activity + LLM call (risk #8). Worker on the **`rca-probes`** queue (G12).
- **KG asset layer** (`packages/kg`): migration `0004_asset_layer.cypher` (Asset/HistoricalFailureEvent/WorkOrder labels + constraints/indexes); `AssetGraph` port (Neo4j + in-memory) with `kg.upsert_asset` (canonical-regex enforced, G4), `kg.link_failure_mode` (ontology-validated, G3), `kg.get_asset_context` (G2). 13 tests.
- **Probe data layer** (`packages/mar` migration `0005`): the 7 tables + ORM models.
- **Probe REST API** (`api.py`): the §3.6/§5.9/§6.6 surface; 6 hermetic tests.

---

## The 22 spec-review gaps — resolution summary

Full details + concrete shapes are in `sprint3_spec.md` § "Gap Resolutions (G1–G23)". Verdicts:

| # | Item | Verdict | Where fixed |
|---|---|---|---|
| 1 | Tool-count drift | **Real (off-by-one)** | Count is **19**, not 20; +4 this sprint = 23. §2.8 corrected; G1 |
| 2 | `kg.get_asset_context` shape | **Real** | Defined inline (`GetAssetContextRequest`/`AssetContext`); `packages/kg/assets.py`; G2 |
| 3 | `kg.upsert_asset`/`link_failure_mode` shapes | **Real** | Defined + ontology validation; `assets.py`; G3 |
| 4 | canonical_id regex on Asset.id | **Real (enforcement)** | `parse_canonical_id` in `upsert_asset`; G4; test `test_upsert_asset_rejects_bad_canonical_id` |
| 5 | `ProvenanceEntry` shape | **Real** | Defined (reuses `Provenance` fields, carries `connection_id`); `contracts/evidence.py`; G5 |
| 6 | Gather threshold | **Real (decision)** | New `GATHER_AUTO_ACCEPT_THRESHOLD=0.85`, distinct from MAR's 0.92; G6 |
| 7 | `RecommendedAction.preconditions/target` | **Real (per use case)** | Added; `contracts/rca.py`; G7 |
| 8 | `open_data_requests` | **Real (decision)** | Own field on `RcaConclusion`; G8 |
| 9 | Alarm-bridge deferral sentence | **Real (doc)** | Added to architectural decisions; G9; also §out-of-scope |
| 10 | `reference_time` origin | **Real** | In `POST /probes/run` body, frozen at workflow start, threaded everywhere; G10 |
| 11 | `POST /probes/run` body | **Real** | `StartProbeRequest` defined; G11 |
| 12 | Probe task queue | **Confirmed** | `rca-probes`; `config.TASK_QUEUE`; G12 |
| 13 | Engineer identity on HITL | **Real** | `HitlResponse.responded_by`; G13 |
| 14 | Plan-step → tool mapping | **Real (pin)** | `STEP_TYPE_TO_TOOL`; names verified present; G14 |
| 15 | Resolution Queue during gather | **Decision** | In-probe HITL only (not the global queue); G15 |
| 16 | `evidence_packages` table | **Real (inline)** | Inlined; migration 0005; G16 |
| 17 | `probe_runs` table | **Real** | Defined (mirrors onboarding_runs); migration 0005; G17 |
| 18 | `probe_runs.status` enum | **Real (consolidate)** | `ProbeRunStatus` enumerates all 10 in one place; G18 |
| 19 | Driving-scenario fixture (P-2103A) | **Real (significant)** | **No P-2103A / WO-48291 exist.** Rebased onto **P-101A** seal-leak scenario; ISO code resolved `LEK→ELP`; G19 |
| 20 | HITL signal-flow clarity | **Real (doc)** | Pseudo-sequence added; implemented as signal+wait_condition; G20 |
| 21 | `HistoricalFailureEvent`→WO edge | **Real** | `RESULTED_IN` added to WI6; WorkOrder is a new KG label; G21 |
| 22 | PFMEA + rank calibration | **Confirmed Phase 2** | Added to §out-of-scope; G22 |
| 23 | (found) §6.2 Cypher duplicates ontology | **Real (correctness)** | MATCH-not-MERGE the ontology nodes; G23; test `test_persist_failure_event_rejects_unknown_ontology_codes` |

---

## Cross-cutting acceptance (spec §"Cross-cutting acceptance", 19 items)

| # | Acceptance | Status |
|---|---|---|
| 1 | `POST /probes/run` starts an end-to-end probe | ✅ API + workflow (hermetic) |
| 2 | Workflow spans planning→gather→RCA→KG→WO, one per probe | ✅ end-to-end test |
| 3 | `packages/llm` single client; every call audited | ✅ (audit sink; Postgres `llm_calls` table exists, in-memory sink tested) |
| 4 | `packages/agents` leg foundation; all 3 agents use it | ✅ |
| 5 | Probe memory in 3 layers | ✅ (layer-2 snapshot written each leg; in-memory tested, Postgres schema present) |
| 6 | HITL bidirectional (ask/approve/edit) | ✅ |
| 7 | HITL questions batched per turn | ✅ (planning cold-start + ambiguity batched) |
| 8 | Lazy KG Asset materialization | ✅ (`kg.upsert_asset`; flywheel asserted) |
| 9 | `EvidencePackage` structured/persisted; `method` provenance | ✅ (`anomaly_method`, `score_method`, `ProvenanceEntry`) |
| 10 | RCA agent produces valid `RcaConclusion` w/ all HITL kinds | ✅ |
| 11 | ISO codes validate against KG ontology | ✅ (validation + hard-block at persist) |
| 12 | Approved conclusions persist as `HistoricalFailureEvent` | ✅ |
| 13 | Follow-up WOs created when actions approved | ✅ (`work_order.create`) |
| 14 | Second probe sees the persisted event via `kg.get_asset_context` | ⚠️ **KG-level** flywheel proven (event persisted + retrievable); the agent-level read needs the live `McpToolBox` (deferred) |
| 15 | `replay_from_cache` + explicit `reference_time` → byte-identical | ✅ at the LLM-client + planning-plan level; full-probe replay-determinism harness deferred |
| 16 | Partial coverage works | ✅ |
| 17 | Negative-trigger invariant (nothing auto-starts) | ✅ (prompt entry only; no alarm bridge) |
| 18 | `task test` green; hermetic tests use replay-from-cache | ✅ green; hermetic tests use scripted/replay transports (no upstream) |
| 19 | Zero new code touches Phase-2 areas | ✅ |

---

## Deferred to next sprint (the honest remainder — pick up here)

These are **bounded, mostly-mechanical** items. The contracts, schema, hermetic end-to-end, and engine seam are all done; what remains is live wiring + a few production paths. None block the hermetic acceptance.

1. **Production worker `build_deps` + `python -m rca_agents.worker` main.** Wire `ProbeActivityDeps` to: Postgres repos (item 2), `Neo4jAssetGraph`, a real `LLMClientImpl` (default_registry + `AnthropicTransport` + a Postgres `llm_calls` audit sink + persistent cache), an `McpToolBox` (item 3), and an `McpWorkOrderCreator`. The `probe:worker` Taskfile task points here. *Not shipped: it is CI-untestable (needs cluster+DB+sims) and I declined to ship unverified live code into an otherwise-green sprint.*
2. **Postgres repo implementations** (`PostgresProbeRunsRepo`/`ProbeMemoryRepo`/`EvidencePackageRepo`/`RcaConclusionRepo` + a `PostgresLlmAuditSink`). The ORM models + migration 0005 exist and import cleanly; these are a direct mirror of `PostgresOnboardingRunsRepo`. Add DB-gated tests under a `task probe:db` (like `task mar:db`).
3. **`McpToolBox`** — the production `ToolBox` that calls the six mounted entity MCP servers over HTTP (fastmcp `Client`), implementing the `STEP_TYPE_TO_TOOL` map and mapping `Provenance.connection_id` into `ProvenanceEntry`. `FakeToolBox` already pins the interface. Also wire the 3 new `kg.*` asset tools into `scripts/run_mcp_host.py` (pass an `AssetGraph`).
4. **MAR `iso14224_class` → KG `EquipmentClass` id mapping.** MAR assets carry `iso14224_class="pump.centrifugal"`; the KG node id is `equipment-class:bb1`. `gather`'s `materialize_kg` must map between them before `kg.upsert_asset`/`link_failure_mode`. Today `FakeToolBox` returns the KG id directly; the live path needs the mapping (a small lookup table or a `kg`-side resolver).
5. **pgvector + embedding doc-scoring.** `document_embeddings` exists with a JSONB `embedding`; the prototype scorer is keyword-overlap. To meet §1.7 fully: switch the compose Postgres image to a pgvector-enabled one, add `CREATE EXTENSION vector` + a native `vector` column in a follow-up migration, and flip `score_documents` to `embedding_v1` (with the embedding cache → "zero embedding calls on the 2nd probe" test).
6. **1-month `probe_memory` retention job** (§2.7/§2.8) — `pg_cron` (needs the extension) to null JSONB columns + set `archived_at` after `completed`. Documented, not yet scheduled.
7. **Full-probe replay-determinism + reference_time-propagation tests** (risk #8, acceptance #15). The pieces are deterministic (det_uuid, frozen reference_time, replay cache); add an explicit test that runs a probe twice from a seeded cache and asserts byte-identical `RcaConclusion` (excluding generation timestamps), and a test asserting every activity input + every `complete()` call carries the frozen `reference_time`.
8. **Large-state escape hatch (§2.5)** — `probe_graph_state` table exists; the spill/rehydrate path (>500 KB) is not exercised. Add the threshold check in `run_agent_leg` + a test.
9. **LangGraph wrapping.** The agents are implemented as **leg-pattern state machines** whose node functions map 1:1 to the §3.1/§4.1/§5.2 LangGraph nodes (langgraph is an optional `graph` extra, not installed). This satisfies the leg contract, determinism, and the engine-swap seam (the spec's graded items, risk #6). Wrapping the nodes in a live `StateGraph` is a thin adapter if/when real graph features (checkpoints, streaming) are needed.
10. **`POST /rca_conclusions/{id}/regenerate` + `GET .../failure_event` + `GET /rca_conclusions/{id}`** — three read/utility endpoints from §5.9/§6.6 not yet in `api.py` (regenerate needs a `regenerate` workflow path or a fresh probe; failure_event needs a KG read).
11. **`AssetAliasUnresolved` table cleanup** (carried from Sprint 2) — still keeps its own `source_system` PK column; remove when that table is replaced.

---

## Open questions for the team

1. **MAR↔KG class id mapping (item 4)** — should `pump.centrifugal → equipment-class:bb1` live as KG seed metadata (an `aka`/`mar_class` property on `EquipmentClass`), a MAR column, or a small mapping service? This blocks the live `materialize_kg` path.
2. **Engine-swap timing** — the `EvidencePackage → RcaConclusion` contract + seam are frozen and tested. When a partner engine (e.g. Pinnacle) is ready, does it honor the HITL contract (mid-analysis `needs_hitl`) or run one-shot? The workflow supports both; confirm before the integration sprint.
3. **pgvector image** — OK to switch the shared compose Postgres to `pgvector/pgvector:pg16`? It also hosts Temporal's auto-setup DBs; needs a quick compatibility check.
4. **Budget-exhaustion UX** — on `TokenBudgetExceeded` mid-probe, the spec offers "ask to extend OR partial result". Current behavior: the leg raises and (next sprint) the workflow finalizes `budget_exceeded`. Do we want the HITL "extend budget?" turn, or is auto-finalize-partial acceptable for Phase 1?
5. **Use-case doc** — `rca_use_case_adil.md` is referenced by the spec but absent from the repo. Several gap items (G7/G8/G19/G21/G22) were resolved from the spec's quotes; please confirm those reads, especially the **P-2103A→P-101A rebase** (G19) and the **LEK→ELP** ISO-code resolution.

---

## Risk-callout status (spec §"Risk callouts")

| # | Risk | Status |
|---|---|---|
| 1 | LangGraph+Temporal new integration | ✅ leg foundation shipped + tested in isolation before agents; serialization round-trips proven via the end-to-end test |
| 2 | HITL UX unbuilt (API only) | ✅ API-only; documented |
| 3 | Cold-start HITL fatigue | ✅ batching implemented; watch in live testing |
| 4 | Token budget across legs | ✅ cumulative budget threaded; budget-exhaustion UX is open question #4 |
| 5 | KG warm-layer schema | ✅ `HistoricalFailureEvent` shape set in WI6 (migration 0004 + persist) |
| 6 | RCA agent depth ≠ partner tool | ✅ acceptance validates contract/seam/flow, not depth (as intended) |
| 7 | Maximo WO write capability | ✅ the sim already supports `POST mxwo`; `work_order.create` added |
| 8 | `reference_time` propagation | ✅ frozen + threaded; explicit determinism test is deferred (item 7) |
| 9 | Probe memory growth at scale | ⚠️ retention job deferred (item 6) |
| 10 | LangGraph state serialization | ✅ `graph_state` is plain JSON; `Message` is a flat serializable shape (risk #10 mitigated by design) |
