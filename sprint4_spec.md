# Sprint 4 Spec — Live Probe & The Flywheel (P-101A, end-to-end)

> **Status:** DRAFT for execution by Claude Code.
> **Branch:** `feat/sprint-4` off `main` (Sprint 3 is merged at `c56c354`).
> **Predecessor:** Sprint 3 shipped the full hermetic probe (478 tests, 6 WIs, 23 gap
> resolutions) against `FakeToolBox` + in-memory repos. Everything in Sprint 3 ran with
> **test doubles**; nothing has executed against the live stack. Sprint 4 makes the probe
> **run for real, twice, and warm up the KG.**

---

## 0. Goal (the single demoable moment)

Type the P-101A prompt → the platform plans → gathers evidence from the **live simulated
sources over MCP** → fires a **mid-analysis HITL** question → produces a ranked RCA
conclusion → **persists** the failure event to the KG and the audit/memory to Postgres →
**a second probe on the same asset reads the first probe's persisted event *through the
agent's* `kg.get_asset_context`.** That second-probe read is the **flywheel** and is the
definition of done (closes Sprint 3 acceptance **#14**).

Everything else (full Postgres persistence, determinism replay) is hardening that makes the
demo production-shaped rather than a happy-path illusion.

---

## 1. Architectural principle (state this; do not violate it)

> **Sources are simulated today and real tomorrow. The data may be simulated, but the
> seams are permanent.** Per `rca_simulator/README.md` and ADR-0012:
> `Agent ──MCP──▶ Connector (ships) ──source-native protocol──▶ rca_simulator (dev) | Real source (prod)`.
> Swapping a simulator for a real source is a **config change, not a code change.**

Implications that bound every work item below:
- The agent reaches data **only** through the `ToolBox` protocol → MCP entity tools. No
  agent code may import a connector, MAR, KG, or a simulator directly.
- `McpToolBox` talks to the **already-existing** MCP servers (MAR, KG, connectors). It must
  not embed source-specific logic; source specifics live behind the connector's MCP seam.
- Anything that differs between "simulated" and "real" must be **endpoint/config**, never a
  branch in agent or `McpToolBox` code.

---

## 2. What ALREADY EXISTS — DO NOT REBUILD

Verified against `main` at spec-writing time. These are **wire-only**; building them again is
out of scope and a defect.

| Component | Location | Status |
|---|---|---|
| `ToolBox` Protocol (12 methods, `(data, ProvenanceEntry)` shape) | `agents/.../toolbox.py:37` | ✅ defined |
| `FakeToolBox` (hermetic fixtures, P-101A seal-leak) | `agents/.../toolbox.py:56` | ✅ keep for tests |
| `STEP_TYPE_TO_TOOL` (G14 plan-step → MCP tool map) | `agents/.../toolbox.py:21` | ✅ done |
| Probe Temporal worker **factory** `make_worker` / `default_agent_factories` | `agents/.../worker.py` | ✅ factory exists; **no `__main__`, no dep construction** |
| `ProbeActivityDeps` (9-field dep bundle) | `agents/.../activities.py:49` | ✅ shape defined |
| **MAR FastMCP server** — `asset.resolve`, `asset.get`, `asset.search` | `mar/.../server.py:58` | ✅ serves entity tools |
| **MAR `PostgresRepository`** (asset side) | `mar/.../repository_pg.py:56` | ✅ **Postgres already done for MAR** |
| **KG FastMCP server** (read tools) | `kg/.../server.py:125` | ✅ serves entity tools |
| **`Neo4jAssetGraph`** (real Neo4j-backed AssetGraph) | `kg/.../assets.py:268` | ✅ **real KG writer exists** |
| KG ISO-14224 BB1 ontology seed (EquipmentClass + CAN_EXHIBIT) | `kg/seed/iso14224_bb1.cypher` | ✅ real, seeded |
| **Connector FastMCP servers** serving `tag.get_history`, `work_order.list_for_asset`, `document.search_for_asset`, `operator_log.list_for_asset` | `connectors/{pi,maximo,documents}/.../server.py` | ✅ serve the exact tool names the agent calls |
| `connector_sdk` MCP helpers (`build_server`, `register`), health, `httpx` client plumbing (errors/retry/context) | `connector_sdk/.../mcp.py`, `context.py`, `errors.py`, `retry.py` | ✅ server helpers + HTTP client plumbing exist |
| **`McpWorkOrderCreator`** (calls `work_order.create` MCP tool over HTTP) **and** `FakeWorkOrderCreator` | `agents/.../wo.py` | ✅ **real WO creator already exists** — wire only |
| Maximo **`work_order.create`** MCP tool (follow-up WO) | `connectors/maximo/.../server.py:219` | ✅ done |
| **Probe + audit DB schema** — migration `0005_probe_tables` creates `probe_runs`, `probe_memory`, `probe_graph_state`, `evidence_packages`, `rca_conclusions`, `llm_calls`, `document_embeddings` | `mar/migrations/versions/0005_probe_tables.py` | ✅ **tables already exist** — implement repos against them, do NOT recreate schema |
| LLM audit module | `llm/.../audit.py` | ✅ exists — inspect before extending |
| **Simulators** (PI, Maximo, SAP PM, OPC UA, documents, MQTT) + coherent `fixtures/refplant/` (P-101A seal-leak scenario, signals, P&ID, datasheets, prior RCAs) | `rca_simulator/` | ✅ real, deterministic-when-seeded |
| `connections_api` registry + state machine + `test_connection` probes | `connections_api/.../` | ✅ |
| Repo **Protocols** + **in-memory** impls (ProbeRuns, ProbeMemory, EvidencePackage, RcaConclusion) | `agents/.../repos.py` | ✅ Protocols + InMemory only |
| RCA agent mid-loop HITL (signal + `wait_condition`) | Sprint 3 WI5 | ✅ implemented hermetically — Sprint 4 exercises it live |
| Engine-swap seam (`EvidencePackage → RcaConclusion`) | Sprint 3 WI5 | ✅ proven; **out of scope** (no partner; agent is internal, Phase 2 later) |

**Out of scope entirely for Sprint 4:** partner-engine integration; LangGraph `StateGraph`
wrapping; new connectors; UI work; multi-asset/alarm-bridge features.

---

## 3. Locked decisions (carry into implementation)

- **D1 — Equipment-class binding (was open Q1).** Canonical *asset* id is minted by MAR and is
  the only id the KG ever sees (already true). The **equipment class** must also be resolved to
  the **KG vocabulary** (`pump.centrifugal` → `equipment-class:bb1`) **once, at MAR asset
  registration**, and persisted MAR-side. The agent always hands `kg.upsert_asset` a KG-native
  class id. The silent-skip in `kg` asset upsert (when the EquipmentClass node is not found)
  becomes a **hard error** — an unresolved class must never orphan an asset silently.
- **D2 — RCA agent is internal and honors mid-analysis `needs_hitl`.** No partner this sprint.
  The live demo **must** show the RCA agent pausing mid-5-Whys for a human-knowledge question.
- **D3 — pgvector image.** Switch the shared compose Postgres to `pgvector/pgvector:pg16`.
  **Verify Temporal auto-setup still works on that image** (explicit task, not an assumption).
- **D4 — Budget exhaustion.** On `TokenBudgetExceeded` mid-probe: **auto-finalize-partial**,
  terminal status `budget_exceeded`, surface the partial result. No "extend budget?" HITL turn.
- **D5 — Transport.** `McpToolBox` reaches entity data over **real MCP/HTTP** to the existing
  MAR/KG/connector servers — not an in-process shortcut.
- **D6 — Connection routing (the source-binding layer).** The object-class tools already route
  to a source via `ConnectionRouter` (`connector_sdk/routing.py`), but the only impl today is
  `StaticConnectionRouter` (a dict). **For Sprint 4: build the static router from the
  `connections_api` registry's current state at worker startup** (router reflects what's
  connected when the worker boots). A fully dynamic per-call `RegistryConnectionRouter` is
  **deferred to Sprint 5**. Rationale: preserves the architecture and is demoable without a
  live-reconnect requirement.

---

## 4. Work Items

Two tiers. **Tier A (WI1–WI4)** delivers a live, demoable single probe. **Tier B (WI5–WI7)**
hardens it into the full flywheel + persistence + determinism. A partial sprint that lands
Tier A still yields a working demo.

### TIER A — Live single probe

#### WI1 — Live stack orchestration & class-binding (D1, D3)
**Build/Do:**
- **Existing pieces (do not reinvent):** `infra/docker-compose.yaml` already defines Postgres
  + Neo4j; the root `Taskfile.yaml` has `mar:db:up`, `kg:db:up`, migrations, and per-sim
  `up:*` targets; `rca_simulator/Taskfile.yaml` brings up each simulator. **Compose these into
  one `task` target** that brings up the full stack **and adds Temporal** (not currently in
  infra) **and starts the connector + MAR + KG MCP servers** + the worker (WI3).
- Switch the `infra/docker-compose.yaml` Postgres to `pgvector/pgvector:pg16`; **verify
  Temporal auto-setup DBs still initialize** on it (D3).
- Implement **D1**: MAR resolves `iso14224_class` → KG-native `equipment-class:*` id at asset
  registration and persists it. **Anchor the map on the KG seed's `code` field**: each
  `EquipmentClass` node already carries a `code` (`BB1`, `PU`, … in `iso14224_bb1.cypher`).
  Build the finite ISO→KG map as a **KG-owned export** (read the seed/graph, emit
  `{dotted_class → equipment-class:id}`) that MAR consumes at registration — keep ontology
  truth in the KG, not duplicated in MAR. (If a dotted form has no matching node, that's the
  hard-fail in the next bullet.)
- Make the KG asset-upsert **hard-fail** on an unresolved EquipmentClass (replace the silent
  skip).

**Acceptance:**
- `task <up>` brings the whole stack healthy; every connector's `test_connection` passes.
- A registered refplant asset (P-101A) carries the KG-native class id in MAR.
- Upserting an asset with an unknown class **raises**, not skips (unit test).
- Temporal workflows start cleanly on the pgvector Postgres image.

#### WI2 — `McpToolBox` (the live ToolBox adapter) (D5)
**Build:** the production `McpToolBox` implementing the `ToolBox` Protocol by calling the
**existing** MCP servers over HTTP. It maps each of the 12 methods to its MCP tool (per
`STEP_TYPE_TO_TOOL` and the MAR/KG tool names) and returns the `(data, ProvenanceEntry)` shape
with a **non-null `connection_id`** per connector-backed section (G5). Endpoint/config-driven
source routing (so simulated↔real is config only). Compose the MCP client from `fastmcp.Client`
+ the **existing** `connector_sdk` HTTP plumbing (`context.py`/`errors.py`/`retry.py`); there is
no ready-made MCP client class, but do not reinvent the httpx/retry/error layer. Do **not** put
source-specific logic in the toolbox.

**Acceptance:**
- `McpToolBox` satisfies the `ToolBox` Protocol (type-checks; substitutes for `FakeToolBox`).
- Against the live stack, each method returns real simulator-derived data with correct
  provenance (`connection_id` non-null, `record_count` accurate).
- No agent or toolbox code imports a connector/MAR/KG/simulator module directly.

#### WI3 — Worker dependency wiring + `__main__`
**Build (wiring only):** construct the full `ProbeActivityDeps` (all 9 fields) and a runnable
entrypoint (`python -m rca_agents.worker`). **Every dependency object already exists** — this WI
assembles them, it does not build them:
- `llm`: real `LLMClient` transport (already in `rca_llm`)
- `toolbox`: `McpToolBox` (from WI2)
- `asset_graph`: `Neo4jAssetGraph` (exists — wire it)
- `wo_creator`: **`McpWorkOrderCreator` (exists in `wo.py` — wire it; do not rebuild)**
- 4 repos: in-memory acceptable here; Postgres lands in WI5
- `agent_factories`: `default_agent_factories` (exists)

**Acceptance:**
- `python -m rca_agents.worker` boots, registers on `rca-probes`, and serves `ProbeWorkflow`.
- A probe submitted to the live worker reaches the first HITL gate using **real** data.

#### WI4 — Live single-probe walkthrough (P-101A) (D2, D4)
**Do:** drive one end-to-end probe on P-101A against the live stack: prompt → plan → plan-
approval HITL → gather (live tags/WOs/docs/operator-logs) → **mid-5-Whys HITL** (D2) → ranked
RCA conclusion. A scripted/seeded operator answer is fine for the demo.

**Acceptance:**
- One clean live run produces a ranked `RcaConclusion` on the **real** P-101A seal-leak data.
- The **mid-analysis HITL** fires and resumes correctly (D2) — not just the final gate.
- Budget-exhaustion path (D4) verified: a tight budget yields `budget_exceeded` + partial.
- A runbook (`docs/pilot/` or `RUN.md`) documents the exact steps to reproduce the demo.

### TIER B — Hardening to the full flywheel

#### WI5 — Postgres persistence (closes #3, #5)
**Build:** Postgres implementations of the **four** repo Protocols in `repos.py`
(`ProbeRunsRepo`, `ProbeMemoryRepo`, `EvidencePackageRepo`, `RcaConclusionRepo`) plus the
`llm_calls` audit write path. Reuse MAR's existing SQLAlchemy/async patterns
(`repository_pg.py`). **The DB schema already exists** — migration `0005_probe_tables.py`
already creates all probe + audit tables (`probe_runs`, `probe_memory`, `probe_graph_state`,
`evidence_packages`, `rca_conclusions`, `llm_calls`, `document_embeddings`). **Do NOT recreate
the schema**; implement repos against the existing tables (add a migration only if a column is
genuinely missing, and flag it). Inspect `llm/audit.py` before extending the audit path. Wire
these repos into `ProbeActivityDeps` in WI3's entrypoint.

**Acceptance:**
- DB-gated tests: a live probe writes runs, memory snapshots/turns/responses, the Evidence
  Package, the conclusion, and every LLM call to Postgres; all are retrievable.
- Idempotency holds on replay (no dup rows on Temporal activity retry).

#### WI6 — The flywheel: second-probe read (closes #14 — DEFINITION OF DONE)
**Do:** after WI4's probe persists the failure event to the KG (via `Neo4jAssetGraph`), run a
**second probe** on P-101A. Assert the second probe's gather step sees the prior failure event
**through the agent's `kg.get_asset_context`** (`prior_events_on_asset` / `kg_warm` reflects it)
— i.e. through the live `McpToolBox`, not a direct KG query.

**Acceptance:**
- Second-probe `get_asset_context` returns the first probe's persisted event(s); `kg_warm` true.
- Demonstrated end-to-end on the live stack (the headline demo moment).

#### WI7 — Determinism & `reference_time` (closes #15, Risk #8)
**Build:** a full-probe determinism harness: run a probe twice from a **seeded** simulator +
cached LLM and assert a byte-identical `RcaConclusion`. Add a test asserting **every** activity
and LLM call carries the frozen `reference_time` (no wall-clock leakage in workflow/agent code;
the `FakeToolBox._now()` wall-clock note must not exist in any workflow-determinism path).

**Acceptance:**
- Twice-run seeded probe → identical conclusion (hash compare).
- A test fails if any activity/LLM call omits/ignores the frozen `reference_time`.

---

## 5. Cross-cutting acceptance (the "Sprint 4 done" bar)

All must hold **simultaneously on the live stack**:
1. `python -m rca_agents.worker` runs the probe against live simulated sources over MCP.
2. P-101A single probe → ranked conclusion, with **mid-analysis HITL** firing (D2).
3. Equipment class resolves MAR→KG once at registration; unresolved class hard-fails (D1).
4. Full Postgres persistence of runs, memory, evidence, conclusion, and LLM audit (#3, #5).
5. **Flywheel:** second probe reads the first's persisted event via the agent (#14).
6. Determinism: seeded twice-run identical conclusion + `reference_time` everywhere (#15).
7. Budget-exhaustion → `budget_exceeded` + partial (D4); pgvector image runs Temporal (D3).
8. Architectural invariant holds: no agent/toolbox direct imports of source/MAR/KG; sim↔real
   is config only.
9. `ruff` + `mypy` clean; existing 478 hermetic tests still green (no regressions).

---

## 6. Gaps-to-verify (code-true findings driving this sprint)

The executor must confirm each before/while implementing; resolve in a `G`-series like Sprint 3.
- **GAP-1:** `McpToolBox` is referenced in a docstring only — **no implementation exists**. (WI2)
- **GAP-2:** `worker.py` builds over injected deps but has **no `__main__` and constructs no
  deps** — nothing runs the probe live. (WI3)
- **GAP-3:** `repos.py` has **InMemory impls only** for all 4 probe repos; no Postgres. (WI5)
  Note: MAR's asset-side Postgres (`repository_pg.py`) **already exists** — reuse its patterns.
  Note: the **DB schema already exists** (`0005_probe_tables.py`) and `McpWorkOrderCreator`
  **already exists** (`wo.py`) — both are wire/implement-against, not build-new.
- **GAP-4:** Class-vocabulary mismatch — MAR stores `pump.centrifugal`; KG nodes are
  `equipment-class:bb1`; **no mapping exists** anywhere; `kg` asset-upsert **silently skips**
  the `INSTANCE_OF` edge on miss (`assets.py`), which would orphan live assets. (WI1/D1)
- **GAP-5:** `FakeToolBox` pre-resolves the class to `equipment-class:bb1`, so hermetic tests
  never exercised the MAR→KG translation — this is why GAP-4 was invisible. Live runs will hit it.
- **GAP-6:** `Neo4jAssetGraph` exists but is unexercised by a live probe; confirm it satisfies
  the `AssetGraph` Protocol used by `ProbeActivityDeps.asset_graph`. (WI3)
- **GAP-7:** Confirm connector MCP servers serve **all** tool names in `STEP_TYPE_TO_TOOL`
  against live simulators (spot-checked: pi/maximo/documents do). (WI2)
- **GAP-9 (routing):** `ConnectionRouter` exists and is wired into every connector tool call,
  but the only impl is `StaticConnectionRouter` (dict); no registry-backed router. Per D6,
  build the static router from `connections_api` state at startup; defer the dynamic one. (WI1/WI3)
- **GAP-8:** `reference_time` propagation is proven only at component level; no full-probe
  assertion. `FakeToolBox._now()` uses wall-clock by design — ensure no equivalent leak exists
  on the live determinism path. (WI7)

---

## 7. Resolution protocol

Mirror Sprint 3: for each gap or ambiguity discovered during execution, append a numbered
resolution to a **§ Gap Resolutions** section at the end of this file (G-series), citing the
file/line that proves the resolution. Do not silently change scope. If a "wire-only" item in
§2 turns out to need real building, flag it explicitly rather than absorbing it.

## 8. Definition of done

Sprint 4 is done when **all 9 cross-cutting items in §5 hold simultaneously on the live stack**,
with the **flywheel (WI6)** demonstrated end-to-end as the headline. Tier A alone = a working
single-probe demo; full sprint = the warming KG, proven twice.

---

## § Gap Resolutions (G-series, code-true at 2026-06-12, branch `feat/sprint-4`)

Each item below was verified against `main` (HEAD `80d6db0`) before planning. Citations are
`file:line`. Items marked **⚠ SCOPE** are §2 "wire-only" claims that turned out to need real
building — flagged per §7 rather than absorbed silently.

- **G1 (GAP-1, WI2) — `McpToolBox` does not exist.** Confirmed: the only reference is the module
  docstring `packages/agents/src/rca_agents/toolbox.py:5`; `__all__` (`toolbox.py:193`) exports
  only `ToolBox`/`FakeToolBox`/`STEP_TYPE_TO_TOOL`/`ProvenanceEntry`. WI2 builds it.
- **G2 (GAP-2, WI3) — `worker.py` has no `__main__`, constructs no deps.** Confirmed:
  `make_worker(client, deps)` accepts injected deps and returns (does not run) a Worker
  (`worker.py:32-36`); zero `__main__` in `packages/agents/`. WI3 builds the entrypoint + deps.
- **G3 (GAP-3, WI5) — probe repos are InMemory-only**, but the **ORM models and tables already
  exist.** `repos.py` exports only `InMemory*` impls (`repos.py:156-160`). The 7 probe/audit
  ORM classes exist (`packages/mar/src/rca_mar/models.py:208-323`: `ProbeRun`, `ProbeMemory`,
  `ProbeGraphState`, `EvidencePackageRow`, `RcaConclusionRow`, `LlmCall`, `DocumentEmbedding`)
  and migration `0005_probe_tables.py` creates them. WI5 implements Postgres repos against the
  existing ORM/tables using MAR's `repository_pg.py` session-factory pattern.
- **G4 (GAP-4, D1, WI1) — no dotted→KG class map exists; KG upsert silently skips.** MAR stores
  the dotted `pump.centrifugal` (`mar/models.py:79`, col from `0001_initial.py:24`); KG seed
  nodes are `equipment-class:bb1` / `equipment-class:pump` (`kg/seed/iso14224_bb1.cypher:7-8`).
  No mapping exists in either package. `Neo4jAssetGraph.upsert_asset` silently skips
  `INSTANCE_OF` when the class node is missing (`kg/assets.py:310-312`, `FOREACH ... CASE WHEN
  ec IS NULL`); `InMemoryAssetGraph` does the same (`assets.py:151-152`). **Two seed caveats:**
  node ids are the *full* `equipment-class:bb1` (not bare `bb1`, despite the `UpsertAssetRequest`
  field comment at `kg/server.py:51`); and `equipment-class:rotating-equipment` carries **no
  `code`** — a code-anchored export must tolerate that.
- **G5 (GAP-5) — confirmed why GAP-4 was invisible.** `FakeToolBox` hardcodes
  `iso14224_class: "equipment-class:bb1"` in its fixture (`toolbox.py:68`), and the gather agent
  has a hardcoded fallback `... or "equipment-class:bb1"` (`gather_graph.py:133`) that masks an
  unresolved class. WI1 removes that fallback so an unresolved class reaches the (new) hard-fail.
- **G6 (GAP-6, WI3) — `Neo4jAssetGraph` satisfies the `AssetGraph` Protocol.** Protocol at
  `kg/assets.py:67-88` (`upsert_asset`, `link_failure_mode`, `get_asset_context`,
  `persist_failure_event`, `link_resulted_in_wo`); `Neo4jAssetGraph` implements all five
  (`assets.py:268-439`). `ProbeActivityDeps.asset_graph` is typed `Any` (`activities.py:52`) — it
  wires directly. Note `ToolBox.upsert_asset` and `AssetGraph.upsert_asset` are **distinct
  seams** with different kwargs (`confidence/method/reference_time` vs
  `iso14224_class_confidence/iso14224_class_method/probed_at`).
- **G7 (GAP-7, WI2) — all 5 tool names are served; `tag.list_for_asset` exists.** `tag.get_history`
  (pi `server.py:164`), `work_order.list_for_asset` (maximo `:136`), `document.search_for_asset`
  (documents `:103`), `operator_log.list_for_asset` (**pi** `make_operator_log_mcp`, `:287` — NOT a
  separate connector), `work_order.create` (maximo `:219`). Crucially `tag.list_for_asset`
  (pi `:134`, returns `TagInfo{tag_name, role}`) exists, so `McpToolBox.tag_history` fans out
  list→N×get_history→summarize. `MeasurementSeries` carries **only raw points** (`measurement.py`),
  so `mean/max/severity/summary` must be **computed** by `McpToolBox`.
- **G8 (GAP-8, WI7) — `reference_time` path is clean.** The only wall-clock in `rca_agents` is
  `FakeToolBox._now()` (a frozen constant `datetime(2026,3,30,...)`, `toolbox.py:122-125`), used
  for WO/document `queried_at` while tag/operator-log use the passed `reference_time` — an
  inconsistency WI7 should normalize. `workflow.py` uses `workflow.now()` (Temporal-deterministic,
  `:70`). `McpToolBox` must derive `queried_at`/windows from `reference_time`, never wall-clock.
- **G9 (GAP-9, D6, WI3) — only `StaticConnectionRouter` exists; no registry router.** The router
  is consumed **inside connector tool handlers** (`connector_sdk/routing.py`; call sites in each
  connector), so it lives in the **MCP-host** process, not the worker. `run_mcp_host.py:76-100`
  already builds a static dev router pointed at the simulators. D6's "from connections_api state"
  reads `repo.list_connections(status="active")` → `ConnectionInfo`; **no connections seed
  exists**, so WI3 builds the router from the registry with a fallback to the static dev router
  (and a task seeds the 4 refplant connections).
- **G10 ⚠ SCOPE (D5, WI1/WI2) — no MCP server runs over HTTP today.** Connector/MAR/KG are
  in-process `FastMCP` factories with no `__main__`/port/Taskfile target; `scripts/run_mcp_host.py`
  mounts MAR+KG(+4 connectors) but uses an *in-memory* MAR repo and mounts KG **without
  `asset_graph`** (so `kg.get_asset_context`/`upsert_asset` are absent). **Decision (owner
  override of D5/§8):** Sprint 4 uses an **in-process `fastmcp.Client`** over a mounted host (the
  `run_mcp_host` pattern, KG given a real `Neo4jAssetGraph`). `McpToolBox` is built against a
  `fastmcp.Client` so the in-process server object becomes an HTTP URL later as a one-line
  construction swap — preserving the "sim↔real is config-only" seam intent. The full HTTP host +
  `RegistryConnectionRouter` remain the production follow-up (Sprint 5).
- **G11 ⚠ SCOPE (WI3) — `McpWorkOrderCreator` does not exist.** §2/GAP-3 call it "real, wire-only";
  reality: `wo.py` has only `FakeWorkOrderCreator` (`wo.py:18-31`), `McpWorkOrderCreator` is a
  docstring (`wo.py:3`). The Maximo `work_order.create` tool *does* exist (`maximo/server.py:219`).
  WI3 **builds** `McpWorkOrderCreator` against the `WorkOrderCreator` Protocol (`activities.py:42`).
- **G12 (D3, WI1) — Temporal is ALREADY in infra; Postgres is plain `postgres:16`.** §2/WI1's
  "Temporal not in infra" is **stale/false**: `temporal` + `temporal-ui` are defined
  (`infra/docker-compose.yaml:30-59`) and wired via `temporal:up`/`infra:up`
  (`Taskfile.yaml:169-182`). The real D3 change is the image `postgres:16` → `pgvector/pgvector:pg16`
  (`docker-compose.yaml:4`) + verify Temporal auto-setup still initializes. Migration 0005 stores
  `document_embeddings.embedding` as **JSONB** (no `CREATE EXTENSION vector`); nothing this sprint
  requires a real `vector` column, so the swap is image-only this sprint (extension is a follow-up).
- **G13 (correctness) — `ToolBox` has 9 methods, not 12; `STEP_TYPE_TO_TOOL` has 5 entries.**
  (`toolbox.py:37-53`, `:21-27`.) `(data, ProvenanceEntry)` applies only to the 4 read tools.
- **G14 (WI4) — probe entry & HITL bridge already wired.** `POST /probes/run` starts the workflow
  (`api.py:36-49`, body `StartProbeRequest`); `GET .../hitl/pending` queries `pending_hitl_turn`
  and `POST .../hitl/respond` signals `hitl_response` (`api.py:58-74`, `workflow.py:54-64`). The
  mid-5-Whys HITL (D2) is `rca_graph._run_five_whys` → `needs_hitl=True` on `needs_human_knowledge`
  (`rca_graph.py:137-172`). WI4 exercises these live.
