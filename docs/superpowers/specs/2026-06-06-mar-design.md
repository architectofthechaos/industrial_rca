# MAR (Master Asset Registry) — MVP design

- **Date**: 2026-06-06
- **Owner**: gvishnu
- **Implements (slice of)**: [EPIC-012](../../mar/EPIC-012-master-asset-registry.md), [SPEC-011](../../mar/SPEC-011-master-asset-registry.md), [ADR-0011](../../adrs/0011-master-asset-registry.md)
- **Status**: Approved (brainstorm) — ready for implementation plan

## Purpose

The Master Asset Registry owns the canonical mapping between source-system asset identifiers
(Maximo functional locations / equipment, SAP equipment numbers, PI AF paths, UNS Sparkplug
segments) and canonical `AssetID` UUIDs, plus asset hierarchy, ISO 14224 class, and criticality.

This is the first build of MAR. Its concrete goal for the MVP: **stand up a real, Postgres-backed
asset registry, seed it from the authoritative asset register, expose the read/resolve MCP tools, and
replace the connectors' in-memory `SignalResolver`/`SourceBinding` stand-ins for the asset-scoped
connectors (Maximo, SAP PM)** — making those connectors resolve against a real registry end-to-end.

## Scope

### In scope (this build)
- Postgres storage: `assets`, `asset_aliases`, `asset_aliases_unresolved` (SQLAlchemy 2.0 async + Alembic).
- 4-step resolution algorithm (exact → cross-walk → regex → unresolved) with a per-tenant LRU cache.
- MCP tools: `assets.resolve`, `assets.get`, `assets.search`, `assets.get_hierarchy`.
- Seeding from a **product-owned** YAML asset register (the authoritative-import path).
- `MarResolver` (in-process) implementing connector_sdk's `SignalResolver` port; wired into the
  Maximo + SAP PM server factories to replace the in-memory stand-in.
- New canonical contract `AssetDescriptor` (+ resolve I/O models) in `rca_contracts`.

### Out of scope (deferred, documented)
- Live source-driven ingestion (S12.4–S12.6) — the EPIC-002 simulators expose **no asset-discovery
  endpoints** (Maximo: only `mxwo`/`mxsr`/`mxfailrep`; PI: only streams + eventframes), so live
  authoritative-import and PI-AF/UNS cross-walk can't be exercised without first growing the sims.
- Spreadsheet *file* importer (S12.7), SAP-authoritative toggle (S12.8), `classify_iso14224` heuristic,
  `register`/`confirm_alias`/`merge` admin tools (S12.9/10), unresolved-queue UI.
- **Signal-level** resolution (tag → `SignalID`, WebID/NodeId handles, `raw_unit`) — that is TRS's
  domain (EPIC-003). Consequently PI and OPC UA stay on their in-memory resolver until TRS lands.

## Key decisions (locked in brainstorm)

1. **Scope** = core registry + resolver wire-in (above).
2. **Persistence** = Postgres + SQLAlchemy 2.0 async + Alembic. This becomes the shared persistence
   foundation TRS / audit log / overlays will reuse.
3. **Resolver mechanism** = in-process `MarResolver` (no MCP/network hop on the connector resolve
   hot-path; meets the p50 < 5 ms target). The MCP server and the in-process resolver share one
   repository + resolution implementation.
4. **Architecture** = single `packages/mar` package, layered, with a **repository Protocol** seam so
   the resolution algorithm is tested hermetically against an in-memory fake and the Postgres DAO is
   tested against a real docker Postgres (the hermetic-vs-parity split the connectors use).

## Architecture

```
packages/mar/  ->  rca_mar
  models.py        SQLAlchemy 2.0 ORM: assets, asset_aliases, asset_aliases_unresolved
  repository.py    AssetRepository Protocol + PostgresRepository + InMemoryRepository
  resolution.py    resolve_asset(repo, ...) -> AssetResolution  (the 4-step algorithm; pure logic)
  cache.py         per-tenant LRU + 60s TTL wrapping resolve
  resolver.py      MarResolver -> implements connector_sdk SignalResolver port (source_binding)
  seed.py          load the YAML register -> upsert assets (+ synthesized parents) + aliases
  server.py        FastMCP server: assets.resolve / get / search / get_hierarchy (hand-wired)
  config.py        DATABASE_URL + engine/session factory
  seed_data/refplant_assets.yaml   product-owned authoritative register (reference plant)
  migrations/      Alembic
+ rca_contracts:   AssetDescriptor, AssetHierarchyNode, ResolveAssetOutput, ResolveStatus
+ infra/docker-compose.yaml  Postgres service (product DB, separate from the sim compose)
```

Dependency direction: `rca_mar` depends on `rca_contracts` + `rca_connector_sdk` (for the
`SignalResolver` Protocol, `SourceBinding`, `ToolResponse`, provenance, error mapping, `build_server`).
Connector packages do **not** import `rca_mar`; the composition layer injects `MarResolver` into the
connector server factory. Product code never imports `rca_simulator` (ADR-0012).

## Data model

Three tables per SPEC-011 (one Alembic migration).

**`assets`** — `asset_id` (PK, UUID), `tenant_id`, `parent_asset_id` (self-FK, nullable),
`iso14224_class`, `iso14224_level`, `tag`, `service`, `criticality`, `manufacturer`, `model`,
`serial_number`, `commissioned_at`, `decommissioned_at`, `location_description`, `description`,
`created_at`, `updated_at`. Indexes: `(tenant_id, iso14224_class)`, `(tenant_id, parent_asset_id)`,
`(tenant_id, tag)`.

**`asset_aliases`** — `alias_id` (PK), `asset_id` (FK), `tenant_id`, `source_system`, `external_id`,
`valid_from`, `valid_to` (NULL = active), `mapping_source`, `confidence`, `is_primary`, `created_at`,
`confirmed_by`, `notes`. **Partial unique index** on `(tenant_id, source_system, external_id) WHERE
valid_to IS NULL`. This is the table `MarResolver.source_binding` reads (reverse lookup:
`asset_id + source -> external_id`).

**`asset_aliases_unresolved`** — `(tenant_id, source_system, external_id)` PK, `first_seen_at`,
`occurrence_count`, `last_attempt_at`, `candidate_payload` JSONB.

### Canonical contract: `AssetDescriptor` (new, in `rca_contracts`)

Strict/frozen/extra-forbid (house style), mirroring the `assets` columns:
`asset_id, tenant_id, parent_asset_id, iso14224_class, iso14224_level, tag, service, criticality
(Literal["A","B","C","D"]), manufacturer, model, serial_number, commissioned_at, decommissioned_at,
location_description, description`. Canonical because TRS (`SignalDescriptor.asset_id`) and the agent
tiers consume it. Rich nameplate (rated flow/head/rpm) and `template_class`/`version` stay out — those
belong to EPIC-004 templates.

### Register reconciliation (seed-time)

The reference asset register uses values that don't map 1:1 to the contract:
- **criticality**: register `high`/`medium`/`low` → contract `A`/`C`/`D` (map `high→A, medium→C,
  low→D`; `B` reserved). Pinned at seed time.
- **parent_unit**: register names a parent tag (e.g. `UNIT-101`) that isn't itself a pump asset. The
  seeder **synthesizes** parent "unit" assets (`iso14224_class=process_unit`) so `get_hierarchy` has a
  real chain to traverse. `asset_id` comes from each register entry's deterministic `asset_id_seed`.

## Resolution algorithm

`resolve_asset(repo, external_id, source, tenant, *, valid_at=None, min_confidence=0.85) ->
AssetResolution` (Resolved | Ambiguous | Unresolved), per SPEC-011:

1. **Exact** active-alias match (valid at `valid_at`) → confidence + `mapping_source` from the row.
2. **Cross-walk** via other already-resolved sources → confidence `0.85`; **>1 candidate → Ambiguous**.
3. **Regex heuristic** (per-tenant patterns) extracts a `tag` → match by tag → confidence `0.70`.
4. No match → `upsert_unresolved` → **Unresolved**.

**Confidence gate:** the tool reports `status="resolved"` only when `confidence >= min_confidence`
(default `0.85`); below that it returns `status="unresolved"` and queues the external_id for HITL.
Consequence (intended): regex-only matches (0.70) do not auto-bind under the default gate — they route
to human confirmation. Regex patterns for the MVP are a small default set, configurable per-tenant via
a dict passed at construction (not yet a DB table).

**Cache:** per-tenant LRU + 60s TTL wrapping `resolve_asset`, keyed by `(tenant, source, external_id)`.
TTL handles staleness for the MVP; explicit invalidation hooks (for `confirm_alias`/`merge`) are stubbed.

## Repository seam

`AssetRepository` Protocol — methods the resolution, tools, resolver, and seeder need:
`find_active_alias`, `find_crosswalk_candidates`, `find_asset_by_tag`, `get_asset`, `search_assets`,
`get_hierarchy(asset_id, direction, max_depth)`, `source_handle_for(asset_id, source) -> external_id |
None` (the reverse lookup), `upsert_unresolved`, `upsert_asset`, `upsert_alias`.

- **`PostgresRepository`** — SQLAlchemy 2.0 async; `get_hierarchy` via a recursive CTE; enforces the
  partial-unique active-alias constraint.
- **`InMemoryRepository`** — dict-backed; used by hermetic resolution + tool tests.

## MCP surface

Hand-wired FastMCP tools (like the MQTT connector — they read MAR's own repository, not an external
source), reusing `build_server`, `ToolResponse[T]`, `ProvenanceAccumulator`, `map_source_error`:

- `assets.resolve(ResolveAssetInput) -> ToolResponse[ResolveAssetOutput]`
- `assets.get(asset_id, tenant_id) -> ToolResponse[AssetDescriptor]`
- `assets.search(SearchAssetsInput) -> ToolResponse[list[AssetDescriptor]]`
- `assets.get_hierarchy(asset_id, direction, max_depth) -> ToolResponse[AssetHierarchyNode]`

**Deviation from SPEC-011:** the spec embedded `provenance` inside `ResolveAssetOutput`. For
consistency with every other tool, provenance is carried by the **`ToolResponse` envelope** instead;
`ResolveAssetOutput = {status, asset, confidence, mapping_source, alternatives}`.

**Error vs. outcome boundary:**
- `status` `"unresolved"` / `"ambiguous"` are **successful** results (data + provenance, not a ToolError).
- Genuine failures → `ToolError` via `map_source_error`: DB unreachable → `source_unavailable`; bad
  input → `validation_failed`; `assets.get` on a missing `asset_id` → `not_found`.

## Resolver wire-in (the integration deliverable)

- `MarResolver` implements connector_sdk's `SignalResolver` port:
  - `source_binding(asset_id, source)` → `repo.source_handle_for(...)` → `SourceBinding(handle=
    external_id, raw_unit="n/a")`.
  - `resolve(signal_id)` → raises a clear "signals are TRS's domain" error; never hit by asset-scoped
    connectors (the orchestrator only calls `resolve` when a request carries `signal_id`).
- **Backward-compatible** change to `make_maximo_mcp` / `make_sap_mcp`: add optional
  `signal_resolver: SignalResolver | None = None`. If provided, use it; else build
  `InMemorySignalResolver` from `bindings` as today (existing tests untouched).

## Seeding

Product-owned register at `packages/mar/seed_data/refplant_assets.yaml` (the customer's tag-register
in real onboarding), encoding the reference-plant facts. `seed.py` parses it →
`upsert_asset` (synthesizing parent unit nodes) + `upsert_alias` for each of `maximo`/`sap_pm`/`pi_af`/
`uns` (primary, `mapping_source="authoritative_import"`, confidence 1.0), using `asset_id_seed` as the
`asset_id`. The seeded source handles (`CRDU-P101A`, EQUNR `10001234`, …) line up with what the sims
serve because both derive from the same reference plant.

## Testing

Same hermetic-vs-real split as the connectors:
- **Hermetic (no DB):** `resolve_asset` vs `InMemoryRepository` — all 4 paths, temporal validity,
  ambiguity, confidence gate, regex.
- **Contract (no DB):** `AssetDescriptor`/`ResolveAssetOutput` round-trip; the 4 MCP tools through an
  in-memory FastMCP `Client` against an in-memory-repo server — envelopes, provenance, error/outcome
  boundary, `not_found`.
- **DB integration (gated by `task mar:db`):** `PostgresRepository` vs real docker Postgres — CRUD,
  recursive-CTE hierarchy, partial-unique-alias constraint. Skips when Postgres is absent.
- **Resolver wire-in (gated, needs the Maximo sim):** seed an in-memory repo → `MarResolver` →
  `make_maximo_mcp(signal_resolver=…)` → real work orders for P-101A. Proves the stand-in is replaced.

## Infra

- `packages/mar/pyproject.toml`: `rca-contracts`, `rca-connector-sdk`, `sqlalchemy[asyncio]>=2`,
  `alembic`, `asyncpg`, `pyyaml`.
- `infra/docker-compose.yaml`: a Postgres service (product DB, separate from the sim compose).
- `config.py`: `DATABASE_URL` env, localhost async default.
- Alembic migrations under `packages/mar/migrations/`.
- Taskfile targets: `mar:db:up`/`down`, `mar:migrate`, `mar:db` (up→migrate→db-tests→down),
  `test:mar`, `parity:mar-wire`.

## Acceptance (DoD for this build)

1. `assets`/`asset_aliases`/`asset_aliases_unresolved` migrate cleanly; partial-unique active-alias
   constraint enforced; recursive hierarchy fetch works.
2. Resolution algorithm passes hermetic tests across all 4 paths incl. temporal validity + ambiguity.
3. The 4 MCP tools return correct `ToolResponse[...]` (provenance present; `unresolved`/`ambiguous` are
   successes; `assets.get` miss → `not_found`).
4. Seeding the reference register populates 4 pumps + synthesized parent units + all-source aliases.
5. **The Maximo connector, wired with `MarResolver`, returns real P-101A work orders from the sim with
   no static binding** — the in-memory stand-in is genuinely replaced for asset-scoped connectors.
6. `ruff` + `mypy` clean; existing connector tests remain green (backward-compatible factory change).

## Relationship to TRS (next)

`signals.asset_id` will FK to `assets.asset_id`. TRS resolves tags → `SignalDescriptor` (with
`asset_id` + signal-level source handles + `raw_unit`); the PI/OPC UA resolver wire-in completes then.
MAR's Postgres + repository + cache patterns are the template TRS reuses.
