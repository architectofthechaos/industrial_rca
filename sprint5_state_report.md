# Sprint 5 State Report — Live Validation, HTTP Transport & Dynamic Routing

> **Branch:** `feat/sprint-5` off `main` (`e7a6667`). **Status:** all 4 WIs + all 6 cross-cutting
> acceptance items DONE, validated on the live stack with real LLM keys. Spec + G-resolutions:
> `sprint5_spec.md` § Gap Resolutions; WI1 run record: `docs/pilot/sprint5_wi1_live_validation.md`.

## Headline

A full P-101A probe runs **end-to-end over HTTP transport + dynamic registry routing** with a real
LLM: planning → plan-approval HITL → gather → **mid-5-Whys human-knowledge HITL (D2)** → ranked
conclusion → approval → KG failure-event persist, with a **second probe reading the warm KG
(flywheel, #14)** and **full Postgres persistence**. The worker reaches the MCP host over HTTP; the
host routes each tool call from the live connection registry, so connect/disconnect reroutes without
a restart.

## Work items

| WI | Decision | Outcome |
|---|---|---|
| **WI1** | D7 — live validation is the entry gate | ✅ All Sprint-4 gated paths pass live (smoke, walkthrough+D2 HITL, budget/D4, flywheel/#14, whole-probe Postgres). **8 latent defects found + fixed** (G20–G27). |
| **WI2** | D8 — HTTP transport (closes G10) | ✅ Worker → host over HTTP (`MCP_HOST_URL`); walkthrough + flywheel both green over HTTP (78 `POST /mcp`); config-only swap. |
| **WI3** | D9 — host isolation + health (Risk #5) | ✅ Per-tool isolation (test); live `GET /health` (6 mounts, 27 tools); prod one-process-per-server path documented. |
| **WI4** | D10 — dynamic routing | ✅ `RegistryConnectionRouter` per-request; 4 rules tested; live disable→reroute-without-restart; live probe over the dynamic router. |

## Gap resolutions

G20–G27 (WI1 live-surfaced defects) + the WI2–WI4 notes are in `sprint5_spec.md` § Gap Resolutions.
The WI1 fixes, in one line each:

- **G20** opus-4-8 rejects `temperature` → transport retries-without + memoizes per model.
- **G21** `search_assets` picked "RCA" not "P-101A" → tag-token regex + asset-list fallback.
- **G22** gated tests read `.status` on a dict (untyped handle) → dict access.
- **G23** Neo4j `DateTime` props fail Pydantic on warm read → coerce to native datetime.
- **G24** `tag.get_history` stored=550k pts/tag → request `interpolated` (~10k, ~0.6s).
- **G25** real-LLM key/enum drift crashed the RCA leg → tolerant parsing + `_one_of` enum guards.
- **G26** invalid LLM mechanism failed persist → seed `failure-mechanism:other` + coerce.
- **G27** default budget 50k/10k too small for a real probe → 400k/50k.

## Verification

- Hermetic: **547 passed / 11 skipped** (was 518 at Sprint-4 merge; ~30 new regression + WI tests).
- `ruff` clean; `mypy` clean across product packages **both with and without** the `rca-llm[live]`
  extra (the SDKs being installed surfaced + we fixed the Voyage/enum types).
- Live (real keys, full stack): all gated suites green over in-process **and** HTTP transport;
  `/health` 200; dynamic disable→reroute proven on a never-restarted host.

## Deferred to Sprint 6

- Real pgvector `vector` column (`document_embeddings` stays JSONB); `PostgresResponseCache`.
- **MAR-backed asset gateway** so the CMMS `work_order.list_for_asset` resolves the maximo_location
  live (today the slug-only gateway raises → gather skips WO evidence; the probe still completes).
- Feed the valid `failure-mechanism:*` vocabulary to the rank-hypotheses prompt (so the LLM picks a
  specific mechanism, not the `other` fallback from G26).
- **Test isolation:** some non-hermetic/DB test wiped the live `rca_mar` assets mid-session
  (re-seeding restored them) — find and fix it so the live store isn't clobbered by the test suite.
