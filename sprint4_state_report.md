# Sprint 4 State Report — Live Probe & The Flywheel

> **Branch:** `feat/sprint-4` off `main` (`80d6db0`). **Status:** Tier A + Tier B code complete
> and hermetically + DB-verified; the live-LLM probe acceptance is written, gated, and documented
> for reproduction (no API keys in this pass — see G19). Plan:
> `docs/superpowers/plans/2026-06-12-sprint4-live-probe-flywheel.md`.

## What shipped (by work item)

| WI | Deliverable | Status |
|---|---|---|
| **WI1** | pgvector image (D3); KG-owned dotted→`equipment-class:*` export (`rca_kg/class_map.py`) + dotted seed alias + migration `0005_class_dotted_alias.cypher`; KG upsert **hard-fails** on unresolved class (both impls); MAR persists `iso14224_class_kg` at registration (migration `0006`); gather hardcoded-`bb1` fallback removed; `stack:up` umbrella target | ✅ done; D1/D3 verified live |
| **WI2** | `McpToolBox` over `fastmcp.Client` — all 9 ToolBox methods, the `tag.list_for_asset`→N×`tag.get_history`→summarize fan-out, MAR→KG class bridge, raise-on-error reads, generic severity rule; §8 no-source-imports invariant test | ✅ done (hermetic, stub-host) |
| **WI3** | `host.py` composition root (MAR + KG**+asset_graph** + 4 connectors, registry-or-static router, no-prefix mount); `McpWorkOrderCreator`; `build_probe_deps` + `python -m rca_agents.worker` entrypoint; refplant connection seed + connector health check | ✅ done; live MCP path verified (all connectors healthy) |
| **WI4** | Live walkthrough + first-HITL smoke tests (stack-gated); **D4 budget-exhaustion implemented** in the workflow + hermetic test; `RUN.md` runbook | ✅ code done; D4 verified hermetically; live walkthrough gated |
| **WI5** | `PostgresLlmAuditSink` + 4 Postgres probe repos (`PgProbeRunsRepo`/`PgProbeMemoryRepo`/`PgEvidencePackageRepo`/`PgRcaConclusionRepo`); `use_postgres=True` deps wiring | ✅ done; **DB-gated tests green against live Postgres** |
| **WI6** | Flywheel second-probe-read test reading through `kg.get_asset_context` over MCP (stack-gated) | ✅ written + gated; live run deferred |
| **WI7** | Full-probe determinism harness (byte-identical `RcaConclusion` twice, real RCA agent); `reference_time`-everywhere AST + behavioral guards | ✅ done (hermetic, green) |

## Acceptance (§5) status

1. `python -m rca_agents.worker` runs the probe over MCP — **entrypoint built**; live run needs keys (G16/G19).
2. P-101A single probe + mid-analysis HITL (D2) — **written + gated**; live run deferred (G19).
3. MAR→KG class binding once at registration; unresolved hard-fails (D1) — ✅ **verified** (unit + live migration).
4. Full Postgres persistence (#3/#5) — ✅ **DB-gated repo/audit tests green**; whole-probe persistence gated (G19).
5. Flywheel second-probe read (#14) — **written + gated**; live run deferred (G19).
6. Determinism + `reference_time` (#15) — ✅ **hermetically verified** (see G17 for the seed contract).
7. Budget-exhaustion → `budget_exceeded` + partial (D4) — ✅ **built + hermetically verified** (G15); pgvector runs Temporal (D3) — ✅ **verified live**.
8. §8 invariant (no agent/toolbox source imports; sim↔real config-only) — ✅ **enforced by test** (G10 in-process transport is an owner-approved deviation, kept HTTP-swap-ready).
9. `ruff` + `mypy` clean; hermetic suite green — ✅ **ruff clean; mypy clean (137 files); 518 passed / 10 skipped** (was 478; +40 new, no regressions).

## Gap resolutions

G1–G14 (pre-execution, verified against `main`) and G15–G19 (discovered during execution) are recorded
in `sprint4_spec.md` § Gap Resolutions. Headlines: **G10** (in-process `fastmcp.Client`, owner override
of D5, HTTP-swap-ready), **G11** (`McpWorkOrderCreator` built — did not exist), **G12** (Temporal already
in infra; D3 = pgvector image swap), **G15** (D4 budget-exhaustion was unimplemented — now built).

## Deferred (next sprint / follow-ups)

- **Live-LLM acceptance run** (D2 walkthrough, WI6 flywheel, WI5 whole-probe persistence): needs
  `rca-llm[live]` + `ANTHROPIC_API_KEY`/`VOYAGE_API_KEY` + a running worker — run `RUN.md` (G16/G19).
- **Production HTTP MCP host + `RegistryConnectionRouter`** (Sprint 5): `host.py`/`McpToolBox` are
  built against `fastmcp.Client` so this is a Client-construction swap, not a rewrite (G10).
- **Real pgvector `vector` column** for `document_embeddings` (still JSONB; image now supports it).
- **`PostgresResponseCache`** for cross-process determinism replay (only `InMemoryResponseCache` today).
- Minor: warn-on-SDK-fallback log in `deps.build_llm`; `RcaConclusion.llm_call_ids` is written `None`
  (no contract field) — thread through if needed.
