# TRS — MVP build notes

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

Durable record of the first Tag Resolution Service build (EPIC-003, MVP slice). Spec:
`docs/superpowers/specs/2026-06-06-trs-design.md`; plan: `docs/superpowers/plans/2026-06-06-trs.md`.

## What was built

New product package `packages/trs` (`rca_trs`) + the `ResolveTagOutput` contract. Mirrors MAR's shape.

- **Contracts** (`rca_contracts`): `ResolveTagOutput` (`SignalDescriptor` already existed).
- **Storage**: SQLAlchemy 2.0 async models (`signals`, `signal_aliases`, `signal_alias_unresolved`) +
  Alembic initial migration. `signal_aliases` carries a **`raw_unit`** column (extends SPEC-003 — the
  connectors' `SourceBinding` needs the source-emitted unit). Partial-unique active-alias index on
  **`(tenant, source, raw_tag, signal_id)`** — see the ambiguity note below.
- **Repository seam**: `SignalRepository` Protocol + `InMemoryRepository` (hermetic) +
  `PostgresRepository` (async). `_active` mirrors the SQL temporal predicate exactly (MAR parity lesson).
- **Resolution**: 4-step (exact → **asset-hinted** → regex → unresolved) + confidence gate + LRU/TTL cache.
- **MCP server**: hand-wired `trs.resolve_tag` / `trs.search_signals` / `trs.get_signal` with
  `ToolResponse[T]` + provenance; `unresolved`/`ambiguous` are successes; `get_signal` miss → `not_found`.
- **Seeding**: product-owned `packages/trs/seed_data/refplant_signals.yaml` → `seed_from_register` upserts
  signals + per-source aliases (`raw_tag` + `raw_unit`). `asset_id`s match MAR's reference assets.
- **Resolver wire-in**: `TrsResolver` implements the **full** `SignalResolver` (`resolve` +
  `source_binding`); the **PI + OPC UA** factories gained an optional `signal_resolver=` (backward
  compatible). This replaces the in-memory stand-in for the signal-scoped connectors.
- **Infra**: `rca_trs` database on the shared Postgres (init script `infra/initdb/01-create-trs-db.sql`)
  + Taskfile `trs:db` / `trs:migrate` / `test:trs` / `parity:trs-wire`.

## Ambiguity model (key TRS-vs-MAR difference)

Unlike MAR (one active alias per external_id), **TRS allows the same `raw_tag` to map to multiple
signals at once** — that is exactly the *ambiguous* resolution case (SPEC-003 step 1). So:
- active uniqueness is per **`(tenant, source, raw_tag, signal_id)`**, not per `(raw_tag)`;
- `find_active_aliases` returns a **list** (possibly >1);
- `upsert_alias` supersedes only the prior active row for the **same signal**, leaving sibling
  signals' aliases intact;
- resolution returns `ambiguous` (with `alternatives`) when >1 signal matches and no `asset_hint`
  disambiguates. (This was caught + corrected during the build before the Postgres task ran.)

## Verification

- Whole product: **116 passed, 14 skipped** (live-service gates skip without sims/DB). `ruff` + `mypy`
  clean (**72 source files**).
- `task trs:db` (real Postgres `rca_trs`): migrations apply; roundtrip, search, **multi-signal-per-tag
  ambiguity + per-signal supersede + partial-unique** all pass. ✅
- `task parity:trs-wire` (real OPC UA sim) — **capstone**: `TrsResolver` (seeded) drives
  `opc_ua.get_current_values` with **no static binding** → real current value (psig→Pa via the resolved
  `raw_unit` + signal metadata). The signal-scoped stand-in is replaced, end-to-end. ✅ PI wire-in
  verified hermetically (in-process PI fake).

## Decisions / boundaries

- **Own database `rca_trs`** on the shared Postgres; `signals.asset_id` is a **soft UUID reference** to
  MAR (no hard cross-DB FK) — keeps TRS's package/migration independent (deviation from SPEC-003's FK).
- **Full resolver** (resolve + source_binding) — completes PI/OPC UA wire-in. `raw_tag` = the source-side
  query handle (OPC UA NodeId clean; PI handle in the register / hermetic).
- **Live wire-in demonstrated via OPC UA** (clean NodeId); PI hermetic (controlled WebID/handle).
- Provenance via the `ToolResponse` envelope (not inside `ResolveTagOutput`) — consistent with all tools.

## Final review (opus, whole-package adversarial) — Approved

No critical/blocking defects; **repository parity solid** (the MAR temporal-divergence lesson applied — both repos' `find_active_aliases` + per-signal `upsert_alias` supersede behave identically, matching the partial-unique index). One Important finding reconciled: step-3 regex narrows by `role` (+ caller `asset_hint`), not by parsing an asset *tag* — because asset-tag→`asset_id` is MAR's domain; the spec wording was tightened to match (no code change — correct by layering). Non-blocking: the LRU/TTL cache is implemented + tested but not yet wired into the resolve path (mirrors MAR; wire when perf demands).

## Deferred (documented, NOT built)

- Live ingestion (S3.4): UNS BIRTH / PI AF browse / Maximo import — sims expose no catalog endpoints
  (same caveat as MAR); tags are seeded from the register.
- `trs.register_signal` / `trs.confirm_alias` admin tools, unresolved-tag queue UI, bulk-resolve API (S3.5/6).
- Cache not yet wired into the resolve path (module exists + tested; wire when perf demands).

## Next

Both resolver seams are now real: MAR backs the asset-scoped connectors (Maximo/SAP), TRS backs the
signal-scoped ones (PI/OPC UA). Natural next: a small composition/onboarding layer that wires both
resolvers behind the connectors, then the agent/workflow tiers (EPIC-005/006/007) that consume these
MCP tools.
