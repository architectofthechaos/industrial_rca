# Sprint 5 WI1 — Live Validation of Sprint 4 (entry gate, D7)

> **Date:** 2026-06-12. **Branch:** `feat/sprint-5`. **Environment:** full local stack
> (`task stack:up` — pgvector Postgres + Neo4j + Temporal + 6 simulators), live worker
> (`PROBE_USE_POSTGRES=1 python -m rca_agents.worker`, in-process MCP host), real Anthropic +
> Voyage keys + `rca-llm[live]` SDKs. Model: `claude-opus-4-8` (+ `claude-haiku-4-5` for summaries).

## Result: all of Sprint 4's previously-gated live work now PASSES LIVE

| Gated path | Test | Live result |
|---|---|---|
| First HITL on real data | `test_live_probe_smoke` | ✅ pass (~32s) |
| Full walkthrough + **mid-5-Whys HITL (D2)** → ranked conclusion | `test_live_probe_walkthrough::test_full_walkthrough_with_mid_analysis_hitl` | ✅ pass (~124s); `plan_approval` + `five_whys` turns both fired; terminal `completed`; `RcaConclusion` (rank-1 primary hypothesis) persisted |
| Budget exhaustion (D4) | `...::test_budget_exhaustion_yields_partial` | ✅ pass; terminal `budget_exceeded`, partial run row, no extend-budget HITL |
| **Flywheel (#14)** — 2nd read sees warm KG via `kg.get_asset_context` over MCP | `test_flywheel` | ✅ pass (~259s); `kg_warm=True`, prior event present |
| Whole-probe Postgres persistence (#3/#5) | DB check on a completed probe | ✅ `probe_runs`/`probe_memory`/`evidence_packages`/`rca_conclusions` = 1 each, `llm_calls` = 14 |

A live P-101A probe makes ~12–14 LLM calls (planning ×2, gather anomaly ×1, fishbone, gaps,
~7 five-whys steps, rank) consuming ~85k input / ~6k output tokens.

## Reproduce

```bash
uv pip install anthropic voyageai            # the rca-llm[live] SDKs
export ANTHROPIC_API_KEY=...  VOYAGE_API_KEY=...
task stack:up                                 # infra + migrations + KG seed + sims + seeds
PROBE_USE_POSTGRES=1 task probe:worker        # in another shell (in-process MCP host)
RCA_STACK=1 uv run pytest packages/agents/tests/test_live_probe_smoke.py \
  packages/agents/tests/test_live_probe_walkthrough.py \
  packages/agents/tests/test_flywheel.py -q
```

## Defects surfaced live and fixed (the entry gate did its job — GAP-4)

These were all invisible to the 518 hermetic tests, which use a *scripted* LLM transport and
*in-memory* doubles. Each was root-caused (systematic-debugging), fixed with a hermetic
regression test, and committed. See `sprint5_spec.md` § Gap Resolutions for detail.

| G | Defect (live-only) | Fix |
|---|---|---|
| G20 | `claude-opus-4-8` 400s on the `temperature` param | `AnthropicTransport` retries without it + memoizes per model |
| G21 | `McpToolBox.search_assets` picked "RCA" (first uppercase token) not the tag "P-101A", and AND-filtered tag+canonical (opposite case) → 0 candidates → IndexError | regex equipment-tag tokens, `tag_pattern` only, fall back to the plant asset list |
| G22 | gated tests read `result.status` on `handle.result()` (a dict via untyped handle) | dict access in walkthrough + flywheel |
| G23 | Neo4j returns datetimes as `neo4j.time.DateTime` → Pydantic rejects on warm-asset read | `_native_props` coerces to native datetime in `get_asset_context` |
| G24 | `tag.get_history` `mode=stored` returned ~550k pts/tag (~25s) → 6 tags blew the 5-min gather-leg timeout (`CancelledError`) | request `interpolated` (~10k pts, ~0.6s) for summary stats |
| G25 | real LLM renames keys (`question`≠`text`) + emits out-of-vocab Literal enums (`question_type`, `priority`, `answer_source`, fishbone `category`) → RCA leg crash | tolerant key parsing + `_one_of` case-insensitive enum guards |
| G26 | LLM picks `iso14224_mechanism='PLU'` (not a KG mechanism); `persist_failure_event` hard-failed | seed `failure-mechanism:other` + coerce unknown mechanisms to it (still MATCHes, never forks the ontology) |
| G27 | default token budget (50k/10k, hermetic-sized) too small for a real probe (~85k input) → every live probe tripped `budget_exceeded` | raise `ProbeWorkflowInput` defaults to 400k/50k |

## Open / flagged (not blocking WI1; carried forward)

- **CMMS work-order tool fails live (deferred).** `CanonicalSlugAssetGateway.source_handle`
  raises by design (no slug rule for a CMMS location); the in-process host wires this slug-only
  gateway, so `work_order.list_for_asset` errors and gather skips WO evidence. A **MAR-backed
  gateway** (resolve the maximo_location from MAR aliases) is needed for live WO evidence —
  medium scope, flagged for Sprint 5 WI3/WI4 or Sprint 6. The probe completes without it.
- **Mechanism vocabulary not given to the LLM (quality).** G26 makes persist robust, but the
  rank-hypotheses prompt should be given the valid `failure-mechanism:*` ids so the LLM picks a
  *specific* mechanism instead of falling back to `other`. Sprint 6.
