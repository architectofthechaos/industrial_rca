# MAR — MVP build notes

Durable record of the first Master Asset Registry build (EPIC-012, MVP slice). Spec:
`docs/superpowers/specs/2026-06-06-mar-design.md`; plan: `docs/superpowers/plans/2026-06-06-mar.md`.

## What was built

New product package `packages/mar` (`rca_mar`) + the canonical `AssetDescriptor` contract:

- **Contracts** (`rca_contracts`): `AssetDescriptor`, `AssetHierarchyNode`, `ResolveAssetOutput`,
  `ResolveStatus`, `Criticality` (strict/frozen).
- **Storage**: SQLAlchemy 2.0 async models (`assets`, `asset_aliases`, `asset_aliases_unresolved`) +
  Alembic initial migration, incl. the **partial unique active-alias index**
  (`(tenant, source, external_id) WHERE valid_to IS NULL`).
- **Repository seam**: `AssetRepository` Protocol with two impls — `InMemoryRepository` (hermetic tests)
  and `PostgresRepository` (async SQLAlchemy; recursive hierarchy via an async children/ancestors walk).
- **Resolution**: 4-step algorithm (exact → cross-walk → regex → unresolved) + confidence gate
  (`min_confidence` default 0.85; regex 0.70 routes to HITL by default). Per-tenant LRU+TTL cache
  available (`cache.py`), not yet wired into the resolve path (YAGNI for the MVP).
- **MCP server**: hand-wired `assets.resolve` / `assets.get` / `assets.search` / `assets.get_hierarchy`,
  reusing the connector_sdk envelope/provenance/error-mapping. `unresolved`/`ambiguous` are successful
  results; `assets.get` on a missing id → `ToolError(not_found)`.
- **Seeding**: product-owned register `packages/mar/seed_data/refplant_assets.yaml` (the customer's tag
  register in real onboarding) → `seed_from_register` upserts assets (synthesizing parent unit nodes) +
  one primary alias per source. `criticality` words map `high→A, medium→C, low→D`.
- **Resolver wire-in**: `MarResolver` implements connector_sdk's `SignalResolver` port; the **Maximo +
  SAP PM** server factories gained an optional `signal_resolver=` param (backward-compatible — existing
  `bindings=` callers untouched). This replaces the in-memory stand-in for the asset-scoped connectors.
- **Infra**: `infra/docker-compose.yaml` (Postgres 16) + Taskfile targets `mar:db:up/down`, `mar:migrate`,
  `mar:db`, `test:mar`, `parity:mar-wire`.

## Verification

- Hermetic suite green; whole product **88 passed, 11 skipped** (DB + sim gates skip without services).
- `ruff` + `mypy` clean across 61 source files (mypy path now includes `packages/mar/src`).
- `task mar:db` — real Postgres: migrations apply, `PostgresRepository` roundtrip + recursive hierarchy
  pass. ✅
- `task parity:mar-wire` — **capstone**: `MarResolver` (seeded from the register) drives the Maximo
  connector with **no static bindings** against the real Maximo sim → real P-101A work orders
  (`WO-50012345`, `WO-50012402`). The stand-in is genuinely replaced, end-to-end. ✅

## How to run

- Hermetic: `task test:mar` (or `uv run pytest packages/mar`).
- DB integration: `task mar:db` (needs Docker).
- Resolver wire-in vs real sim: `task parity:mar-wire` (needs Docker + the Maximo sim).

## Decisions / boundaries

- **Asset-scoped only.** MAR backs `source_binding(asset_id, source)` for Maximo/SAP. **Signal-level**
  binding (PI WebID / OPC UA NodeId / `raw_unit`) is TRS's domain — PI/OPC UA stay on the in-memory
  resolver until TRS lands. `MarResolver.resolve(signal_id)` raises a clear "TRS domain" error.
- **In-process resolver** (no MCP hop on the connector hot-path) — meets the SPEC-011 p50<5ms target.
- **Provenance via the envelope**, not inside `ResolveAssetOutput` (deviation from SPEC-011, for
  consistency with every other tool).
- **MAR owns its seed register** (vs reading the sim's fixtures) — clean ADR-0012 boundary; the
  reference-plant facts are encoded in both and kept aligned by convention (the wire-in test catches drift).

## Deferred (documented, NOT built)

- **Live source-driven ingestion** (S12.4–S12.6): the EPIC-002 sims expose no asset-discovery endpoints
  (Maximo has only work-order/SR/failure routes; PI has only streams + eventframes). Authoritative import
  + PI-AF/UNS cross-walk need new sim endpoints first.
- Spreadsheet *file* importer (S12.7), SAP-authoritative toggle (S12.8), `assets.classify_iso14224`
  heuristic, `assets.register`/`confirm_alias`/`merge` admin tools (S12.9/10), unresolved-queue UI.
- Cache wiring into the resolve path (module exists + tested; wire when perf demands).

## Next

TRS (EPIC-003): `signals.asset_id` FKs to `assets.asset_id`; TRS reuses MAR's Postgres + repository +
cache patterns and completes the PI/OPC UA signal-level resolver wire-in.
