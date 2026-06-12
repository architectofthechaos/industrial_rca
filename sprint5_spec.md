# Sprint 5 Spec — Live Validation, HTTP Transport & Dynamic Routing

> **Status:** DRAFT for execution by Claude Code.
> **Branch:** `feat/sprint-5` off `main` (`e7a6667`, Sprint 4 merged via PR #1).
> **Predecessor:** Sprint 4 shipped the full live-capable probe (7 WIs, 518 tests, McpToolBox,
> Postgres repos, flywheel + determinism harnesses) — but the **live-LLM runs were gated behind
> `RCA_STACK=1` + API keys and were never executed**, and the McpToolBox→host transport is
> **in-process** (G10), routing is **static-at-startup** (D6). Sprint 5 proves the gated work
> runs for real, then makes the data path production-shaped: HTTP transport + dynamic routing.
> **Out of scope (deferred to Sprint 6):** real pgvector `vector` column + `PostgresResponseCache`.

---

## 0. Goal

Two outcomes, in order:
1. **Prove Sprint 4 live** — with API keys + the full stack, the gated P-101A walkthrough, the
   flywheel, and whole-probe Postgres persistence actually run and pass. This is the entry gate.
2. **Productionize the data path** — swap McpToolBox→host from in-process to **HTTP** (G10),
   address the single-process host-isolation risk (Risk #5), and add a **dynamic
   `RegistryConnectionRouter`** so connect/disconnect in `connections_api` drives routing live.

---

## 1. Architectural principle (unchanged, now enforced over the wire)

> Sources are simulated today and real tomorrow; the seams are permanent. After Sprint 5 the
> **entire chain is HTTP end-to-end** (Agent → McpToolBox → *HTTP* → MCP host → *HTTP* →
> simulators), and **which source answers a tool call is decided per-request from the live
> connection registry**, not frozen at worker startup. Swapping a simulator for a real source
> stays a config change (a different `base_url` registered as the active connection).

---

## 2. What ALREADY EXISTS — DO NOT REBUILD

Verified against `main` at spec-writing time.

| Component | Location | Status |
|---|---|---|
| `McpToolBox` — injected open `fastmcp.Client`, zero transport logic inside | `agents/.../mcp_toolbox.py:62` | ✅ transport-agnostic by design |
| In-process Client construction + `build_entity_host` | `agents/.../host.py` | ✅ in-process today; HTTP is a Client-construction swap |
| HTTP MCP host serving all 6 servers on `:8100/mcp` | `scripts/run_mcp_host.py` | ✅ HTTP host already exists |
| `ConnectionRouter` Protocol (`async def active(...) -> ConnectionInfo`) | `connector_sdk/.../routing.py:39` | ✅ the contract the new router implements |
| `StaticConnectionRouter` + `router_from_connections()` (static snapshot at boot) | `connector_sdk/routing.py:45`, `agents/host.py:58` | ✅ static exists — Sprint 5 adds the dynamic one |
| `connections_api` `list_connections(plant_id, category, status)` + one-active-per-category invariant + lifecycle state machine | `connections_api/.../connections_router.py:88` | ✅ the registry the dynamic router queries |
| `NoActiveConnection` / ambiguity errors (typed `source_unavailable`, non-retryable) | `connector_sdk/routing.py:26` | ✅ reuse verbatim |
| Simulators as FastAPI/uvicorn HTTP servers (PI :8001, Maximo :8002, SAP :8003, Docs :8004) | `rca_simulator/` | ✅ already HTTP |
| `task stack:up` umbrella + `probe:host`/`probe:worker` + `RUN.md` | `Taskfile.yaml`, `RUN.md` | ✅ stack orchestration exists |
| Gated live tests (`test_live_probe_walkthrough`, `test_flywheel`, `test_live_probe_smoke`) | `agents/tests/` | ✅ written + `RCA_STACK=1`-gated — Sprint 5 runs them |

**Out of scope entirely:** real pgvector `vector` column (`document_embeddings` stays JSONB —
Sprint 6); `PostgresResponseCache` (Sprint 6); partner-engine integration; new connectors; UI;
multi-asset/alarm features.

---

## 3. Locked decisions

- **D7 — Live validation is the entry gate.** WI1 runs the gated suite with real keys before any
  new code. Any failure surfaced becomes in-scope Sprint 5 fix work (record as a G-resolution).
- **D8 — HTTP transport (closes G10).** The live worker constructs its `fastmcp.Client` against
  the HTTP host URL (default `http://127.0.0.1:8100/mcp`), config-driven. In-process stays the
  hermetic-test path. No change to `McpToolBox` internals — only how the Client is built.
- **D9 — Host process isolation (Risk #5).** The single-process multi-mount host is acceptable
  for the pilot, but Sprint 5 must (a) add a `/health` + per-tool error isolation so one failing
  tool does not crash the host, and (b) **document** the path to one-process-per-server for prod.
  Full process-per-server is **not** required this sprint — isolation + a documented path is.
- **D10 — Dynamic routing.** Add `RegistryConnectionRouter` implementing the `ConnectionRouter`
  Protocol by calling `connections_api.list_connections(plant_id, category, status="active")`
  **per request** (with a short TTL cache acceptable). It replaces the static snapshot in the
  live worker; `StaticConnectionRouter` remains for hermetic tests and un-seeded dev fallback.
- **D11 — Keys/secrets.** API keys (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`) are provided via env
  by the owner; never commit them. `rca-llm[live]` SDKs installed in the live environment only.

---

## 4. Work Items

### WI1 — Live validation of Sprint 4 (D7) — THE ENTRY GATE
**Do (no new feature code first):** with keys in env + `rca-llm[live]` installed, bring up the
full stack (`task stack:up` + `probe:host` + `probe:worker`) and run the gated suite
`RCA_STACK=1`:
- `test_live_probe_walkthrough` — P-101A end-to-end with real LLM; **mid-analysis HITL fires** (D2).
- `test_flywheel` — second probe reads the warm KG via `kg.get_asset_context` over MCP (#14).
- whole-probe **Postgres** persistence (runs/memory/evidence/conclusion/llm_calls) with
  `use_postgres=True`.

**Acceptance:**
- All three gated paths **pass live** (not skipped). Capture the run output/logs in `docs/pilot/`.
- Any defect found is fixed in this sprint and recorded as a G-resolution; if a fix is large
  enough to threaten scope, flag it rather than absorbing it.
- `RUN.md` updated with the exact verified command sequence + observed results.

> WI1 must complete (green live) before WI2–WI4 transport/routing changes, so we change a
> *known-good* baseline rather than debugging two things at once.

### WI2 — HTTP transport swap (D8, closes G10)
**Build:** config-driven construction of the live worker's `fastmcp.Client` against the HTTP
host URL (env `MCP_HOST_URL`, default `http://127.0.0.1:8100/mcp`). Wire `probe:worker` to start
against the running `probe:host` over HTTP. Keep in-process construction as the hermetic-test
path (no `McpToolBox` internal changes).

**Acceptance:**
- Live worker reaches every entity tool over **HTTP** (verify in host access logs).
- The full WI1 gated suite passes again **over HTTP** (re-run, still green).
- Hermetic suite unchanged (still uses in-process Client); no regressions.
- Flipping `MCP_HOST_URL` is the only change needed to point at a different host (no code edit).

### WI3 — Host isolation + health (D9, Risk #5)
**Build:** per-tool error isolation in `run_mcp_host.py` so a failing/raising tool returns a
typed error response instead of killing the host; add a `/health` (and per-mount readiness)
endpoint. Document in `run_mcp_host.py` (or an ADR) the path to one-process-per-server for prod.

**Acceptance:**
- A deliberately failing tool call returns a typed error; the host stays up and other tools work
  (test).
- `/health` reports host + per-mount status.
- Prod isolation path documented (not implemented).

### WI4 — Dynamic RegistryConnectionRouter (D10)
**Build:** `RegistryConnectionRouter` (in `connector_sdk` alongside `StaticConnectionRouter`)
implementing `ConnectionRouter.active(...)` by querying `connections_api`
`list_connections(plant_id, category, status="active")` per request (short TTL cache allowed).
Preserve the existing resolution rules exactly: explicit `connection_id` wins; single active
used; zero → `NoActiveConnection`; 2+ without explicit id → ambiguity error. Wire it into the
live worker/host (replacing the static snapshot); keep `StaticConnectionRouter` for tests + dev
fallback.

**Acceptance:**
- Router resolves the active source per request from the live registry (test against
  `connections_api`).
- **Dynamic behavior proven:** disable a connection in the registry → the next tool call routes
  differently (or raises `NoActiveConnection`) **without restarting the worker** (the
  static-snapshot limitation is gone).
- All four resolution rules covered by tests (explicit / single / none / ambiguous).
- A live probe still completes end-to-end using the dynamic router.

---

## 5. Cross-cutting acceptance (the "Sprint 5 done" bar)

All hold simultaneously on the live stack:
1. Sprint 4's three gated paths (walkthrough + flywheel + whole-probe Postgres) **pass live** (D7).
2. The live worker talks to the MCP host over **HTTP**; flipping `MCP_HOST_URL` is config-only (D8).
3. The host survives a failing tool; `/health` works; prod isolation path documented (D9).
4. `RegistryConnectionRouter` resolves per-request from the registry; disable→reroute works
   **without a worker restart**; all four resolution rules tested (D10).
5. A full live P-101A probe completes end-to-end over HTTP + dynamic routing (the headline).
6. `ruff` + `mypy` clean; the hermetic suite (518+) still green — no regressions; new tests added.

---

## 6. Gaps-to-verify (code-true; confirm during execution)

- **GAP-1 (G10):** McpToolBox→host is **in-process**; HTTP host exists on `:8100` but the live
  worker doesn't yet construct an HTTP Client. (WI2)
- **GAP-2 (D6 limit):** routing is a **static snapshot** at boot (`router_from_connections()`);
  no per-request registry router exists. (WI4)
- **GAP-3 (Risk #5):** `run_mcp_host.py` mounts all 6 servers in one process with no per-tool
  isolation or health endpoint — one crash takes the host down. (WI3)
- **GAP-4:** the gated live tests have **never been executed** (no keys in CI); "green" today
  means hermetic-only. WI1 is the first real run and may surface latent defects. (WI1)
- **GAP-5 (minor, watch):** `repos_pg.py` writes `llm_call_ids: None` on the conclusion — the
  audit trail isn't threaded through. Not in Sprint 5 scope; note if it blocks live persistence.

---

## 7. Resolution protocol

Mirror Sprints 3–4: append numbered G-resolutions to a **§ Gap Resolutions** section here,
citing file/line. Do not silently change scope. If a WI1 live defect requires a fix beyond
trivial, flag it explicitly with its size before absorbing it.

## 8. Definition of done

Sprint 5 is done when **all 6 cross-cutting items in §5 hold simultaneously on the live stack**,
with the headline being a **full live P-101A probe over HTTP transport + dynamic registry
routing**, and Sprint 4's previously-gated work now **proven live**. pgvector + response-cache
remain explicitly deferred to Sprint 6.

---

## § Gap Resolutions (G-series)

### WI1 — Live validation of Sprint 4 (D7 entry gate): DONE, 2026-06-12

All of Sprint 4's previously-gated paths now **pass live** on the full stack with real keys
(`claude-opus-4-8`/`claude-haiku-4-5`): smoke, walkthrough with the **mid-5-Whys HITL (D2)** →
`completed` ranked conclusion, budget-exhaustion (D4), the **flywheel (#14)**, and whole-probe
Postgres persistence (#3/#5: runs/memory/evidence/conclusion + 14 llm_calls). Run record +
reproduce steps: `docs/pilot/sprint5_wi1_live_validation.md`. The first real run surfaced 8
latent defects the 518 hermetic tests (scripted LLM + in-memory doubles) could not — each
root-caused, fixed with a hermetic regression test, and committed:

- **G20 — `temperature` deprecated on `claude-opus-4-8`.** The model returns
  `400 invalid_request_error: temperature is deprecated for this model`; haiku-4-5 still accepts
  it. `AnthropicTransport.complete` now sends `temperature`, and on a temperature-specific
  `BadRequestError` retries without it and memoizes the model (`transports.py`).
  Forward-compatible, no per-model denylist. Test: `test_anthropic_transport.py`.
- **G21 — `McpToolBox.search_assets` found no asset.** Planning passes the full prompt as
  `keywords`; the old heuristic picked the first uppercase token ("RCA") not the tag "P-101A",
  and double-filtered `tag_pattern`+`canonical_id_pattern` (MAR ANDs them; opposite case) → 0
  rows → `candidates[0]` IndexError in planning. Now extracts equipment-tag tokens via regex
  (digits required), searches `tag_pattern` only, and falls back to the plant asset list so the
  LLM always has a shortlist (`mcp_toolbox.py:_tag_tokens`). Test: `test_mcp_toolbox_search.py`.
- **G22 — gated tests read `result.status` on a dict.** `handle.result()` on an *untyped*
  workflow handle (even with `pydantic_data_converter`) returns the JSON dict, not a
  `ProbeResult`. Fixed to dict access in `test_live_probe_walkthrough.py` + `test_flywheel.py`.
- **G23 — Neo4j temporal props fail Pydantic.** Neo4j returns datetime node properties as
  `neo4j.time.DateTime`, which Pydantic rejects for a `datetime` field — so reading a
  *materialized* (warm) asset back via `get_asset_context` raised `validation_failed`, blocking
  the walkthrough + flywheel. `assets.py:_native_props` coerces temporals via `.to_native()`
  before `model_validate` (asset summary + failure-event summaries). Test: `test_neo4j_temporal.py`.
- **G24 — `tag.get_history` volume blew the gather-leg timeout.** `mode=stored` over a 7-day
  window returns ~550k recorded points/tag (~25s); 6 tags exceeded the 5-min `_LEG_TIMEOUT` and
  Temporal cancelled the in-flight call (`CancelledError`, a `BaseException`, uncaught by gather's
  `except Exception`). `McpToolBox.tag_history` now requests `interpolated` (evenly-spaced,
  ~10k pts/tag, ~0.6s) — the toolbox only needs summary stats. Test: `test_mcp_toolbox_history.py`.
- **G25 — RCA leg crashed on real-LLM output shape.** Anthropic doesn't hard-enforce a prompt's
  JSON schema; the live LLM emitted gap questions keyed `{id,topic,question}` (not
  `{text,question_type}`) and out-of-vocab Literal enums (`question_type="maintenance_history"`,
  fishbone `category="machine"`, `priority`, `answer_source`). Hardened all raw-LLM dict reads in
  `rca_graph.py` — `_question_text` (key variants, drop text-less), `_one_of` (case-insensitive
  enum canonicalization or default) on question_type/priority/answer_source/category, and `.get`
  fallbacks for actions/ODRs/causes. Test: `test_rca_llm_parsing.py`.
- **G26 — invalid mechanism failed the close phase.** The rank-hypotheses prompt is given valid
  failure-MODE codes but never the **mechanism** vocabulary, so the LLM emitted
  `iso14224_mechanism='PLU'` (a failure-mode code) and `persist_failure_event` hard-failed.
  Seeded a generic ISO-14224 `failure-mechanism:other` (migration `0006`) and coerce an unknown
  mechanism to it in both `persist_failure_event` impls — still MATCHes a real node, never forks
  the ontology (G23 invariant intact). Failure MODE still hard-fails (modes ARE given to the LLM).
  Tests: `test_mechanism_coercion.py`, updated `test_seed_content.py` (41→42 mechanisms).
- **G27 — default token budget too small for a real probe.** A full live Opus probe re-sends the
  evidence package across planning+gather+fishbone+gaps+~7 five-whys+rank (~85k input observed),
  blowing the old hermetic-sized 50k/10k default and tripping `budget_exceeded` mid-run. Raised
  `ProbeWorkflowInput` defaults to 400k/50k (`models.py`); the explicit-tight-budget D4 test is
  unaffected.

**Flagged, not blocking WI1 (carried forward):**
- **CMMS work-order tool fails live.** `CanonicalSlugAssetGateway.source_handle` raises by design;
  the host wires this slug-only gateway, so `work_order.list_for_asset` errors and gather skips WO
  evidence (the probe still completes). A **MAR-backed gateway** (resolve `maximo_location` from
  MAR aliases) is needed for live WO evidence — medium scope, candidate for WI3/WI4 or Sprint 6.
- **Mechanism vocabulary to the LLM (quality).** G26 makes persist robust; the rank-hypotheses
  prompt should additionally be given the valid `failure-mechanism:*` ids so the LLM picks a
  specific mechanism rather than `other`. Sprint 6.

### WI2–WI4 — productionize the data path: DONE, 2026-06-12

- **WI2 / D8 / closes G10 — HTTP transport.** The live worker now builds its `fastmcp.Client`
  against `MCP_HOST_URL` (default `http://127.0.0.1:8100/mcp`, served by `task probe:host` =
  `python -m rca_agents.host`); `McpToolBox` unchanged. Validated LIVE: the full walkthrough
  (with D2 HITL) **and** the flywheel both pass over HTTP (host served 78 `POST /mcp` calls);
  pointing elsewhere is `MCP_HOST_URL` only. Hermetic suite still uses the in-process Client.
  (`config.py:mcp_host_url`, `worker.py`, `test_config_mcp_host.py`.)
- **WI3 / D9 / Risk #5 — host isolation + health.** FastMCP isolates a failing tool per-request
  (host stays up; test `test_host_health.py`); added `GET /health` reporting host liveness +
  per-mount readiness (validated live: `status:ok`, 6 mounts, 27 tools); documented the path to
  one-process-per-server (config+deploy, not a rewrite) in `host.py`.
- **WI4 / D10 — dynamic RegistryConnectionRouter.** `RegistryConnectionRouter` (connector_sdk)
  resolves each (plant, category) by querying `connections_api list_connections(status='active')`
  per request (optional TTL cache), delegating the four resolution rules (explicit/single/none/
  ambiguous) to `StaticConnectionRouter` verbatim (hermetic `test_registry_router.py`). The host
  defaults to it (static dev fallback only when the registry is *unreachable*; an empty reachable
  result yields `NoActiveConnection`). Proven LIVE on one never-restarted host: document connection
  **active → 5 docs; disabled → `source_unavailable` (rerouted); re-active → 5 docs** — no worker
  restart (`test_dynamic_routing.py`); and a full live probe completes end-to-end over the dynamic
  router.

**Cross-cutting (§5) — all hold:** Sprint-4 gated paths live (D7); worker over HTTP, config-only
(D8); host survives a failing tool + `/health` + prod path documented (D9); per-request registry
routing + disable→reroute-without-restart + 4 rules tested (D10); full live P-101A probe over HTTP
+ dynamic routing (headline); ruff + mypy clean (with and without the `[live]` extra), hermetic
suite 547 passed / 11 skipped (+~30 new tests, no regressions).

**Deferred to Sprint 6:** real pgvector `vector` column; `PostgresResponseCache`; MAR-backed
gateway for live CMMS work-order evidence; feeding the mechanism vocabulary to the rank-hypotheses
prompt; investigate the test-isolation gap that wiped live `rca_mar` assets mid-session.
