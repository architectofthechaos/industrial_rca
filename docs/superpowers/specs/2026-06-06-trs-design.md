# TRS (Tag Resolution Service) — MVP design

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

- **Date**: 2026-06-06
- **Owner**: gvishnu
- **Implements (slice of)**: [EPIC-003](../../trs/EPIC-003-trs.md), [SPEC-003](../../trs/SPEC-003-tag-resolution-service.md), [ADR-0001](../../adrs/0001-tag-resolution-service.md)
- **Status**: Decisions locked autonomously (user away; decide-and-document, per the same mode as the connector run). Judgment calls flagged inline for later review.

## Purpose

TRS owns the canonical mapping between raw source tag strings and `SignalID` UUIDs, owns signal
identity (`SignalDescriptor`), and provides the per-signal **source binding** (the source-side query
handle + the raw unit the source emits). It is the signal-level analog of MAR (already built) and
**completes the connectors' resolver wire-in**: TRS supplies the full `SignalResolver`
(`resolve(signal_id) -> SignalDescriptor` **and** `source_binding(signal_id, source) -> SourceBinding`)
for the signal-scoped connectors (PI, OPC UA), which currently still use the in-memory stub.

This is the first TRS build. Concrete goal: a Postgres-backed signal registry, seeded from an
authoritative register, exposing the read/resolve MCP tools, with an in-process `TrsResolver` that
replaces the in-memory stand-in for PI + OPC UA — demonstrated end-to-end against the real OPC UA sim.

## Scope

### In scope
- Postgres storage: `signals`, `signal_aliases`, `signal_alias_unresolved` (SQLAlchemy 2.0 async + Alembic).
- 4-step resolution (exact → asset-hinted → regex → unresolved) + per-tenant LRU/TTL cache.
- MCP tools: `trs.resolve_tag`, `trs.search_signals`, `trs.get_signal`.
- Seed from a product-owned signal register.
- `TrsResolver` (full `SignalResolver`: `resolve` + `source_binding`) wired into the PI + OPC UA factories.
- New canonical contract `ResolveTagOutput` in `rca_contracts` (`SignalDescriptor` already exists).

### Out of scope (deferred, documented)
- Live ingestion (S3.4): UNS BIRTH / PI AF browse / Maximo import — the EPIC-002 sims expose no
  discovery/catalog endpoints (same caveat that scoped MAR), so tags are seeded from a register.
- `trs.register_signal` / `trs.confirm_alias` admin tools (S3.5), unresolved-tag queue UI, bulk-resolve
  API (S3.6).

## Key decisions (locked)

1. **Reuse the MAR stack** verbatim in shape: uv package `packages/trs` (`rca_trs`), Postgres +
   SQLAlchemy 2.0 async + Alembic, repository Protocol (`InMemoryRepository` + `PostgresRepository`),
   4-step resolution + LRU/TTL cache, hand-wired FastMCP tools with `ToolResponse[T]` + hard-fail
   provenance + the error/outcome boundary, product-owned seed register, in-process resolver.
2. **Separate database `rca_trs`** on the same Postgres server, with TRS's own Alembic history.
   `signals.asset_id` is a **soft UUID reference** to MAR's `assets.asset_id` — NOT a hard cross-database
   FK. *(Deviation from SPEC-003's hard FK — flagged.)* Rationale: keeps TRS's package + migration fully
   independent of MAR (TRS can migrate/seed/test alone); the logical link holds by convention (the seed
   register uses the same `asset_id`s MAR seeds), and onboarding still populates MAR first. A hard FK can
   be added later if the two are co-managed in one database.
3. **TRS provides the FULL resolver** (unlike MAR, which only did `source_binding`): `TrsResolver.resolve`
   returns the `SignalDescriptor` from the `signals` table; `source_binding(signal_id, source)` returns
   the per-(signal, source) handle + raw unit. This is what lets PI/OPC UA stop using the in-memory stub.
4. **`signal_aliases` gains a `raw_unit` column** (the source-emitted unit, e.g. `psig`). SPEC-003's
   schema stores `raw_tag` but not `raw_unit`; the connectors' `SourceBinding` needs `raw_unit`, and it is
   per-(signal, source), so it belongs on the alias row. *(Minimal extension of SPEC-003 — flagged.)*
5. **`raw_tag` = the source-side query handle the connector uses** (OPC UA NodeId, PI WebID, UNS metric),
   matching how MAR's `external_id` was the connector handle. For OPC UA this is the NodeId string
   (clean/literal). For PI it is the WebID; the register carries the WebID value (in real onboarding the
   PI-AF ingestor would discover it, not hand-author it). *(MVP shortcut — flagged.)*
6. **Live wire-in demonstrated via OPC UA** (clean NodeId handle): `parity:trs-wire` drives
   `opc_ua.get_current_values` through `TrsResolver` against the real OPC UA sim. PI's wire-in is verified
   **hermetically** (a PI fake where the WebID is controlled). Both PI + OPC UA factories get the resolver
   injection; only OPC UA is exercised live (mirrors MAR demonstrating its wire-in via Maximo alone).

## Architecture

```
packages/trs/  ->  rca_trs
  models.py        SQLAlchemy ORM: signals, signal_aliases, signal_alias_unresolved
  repository.py    SignalRepository Protocol + AliasRow + InMemoryRepository
  repository_pg.py PostgresRepository (async)
  resolution.py    resolve_tag(repo, ...) -> TagResolution  (4-step)
  cache.py         per-tenant LRU + 60s TTL
  resolver.py      TrsResolver -> implements connector_sdk SignalResolver (resolve + source_binding)
  seed.py          load the YAML signal register -> upsert signals + aliases
  server.py        FastMCP: trs.resolve_tag / trs.search_signals / trs.get_signal (hand-wired)
  config.py        DATABASE_URL (default rca_trs) + engine/session factory
  seed_data/refplant_signals.yaml   product-owned signal register (reference plant)
  migrations/      Alembic (own version table)
+ rca_contracts:   ResolveTagOutput (SignalDescriptor already exists)
+ infra/:          add an rca_trs database to the existing Postgres (init script)
```

Dependency direction: `rca_trs` → `rca_contracts` + `rca_connector_sdk`. Connector packages do NOT import
`rca_trs`; the composition layer injects `TrsResolver`. Never imports `rca_simulator` (ADR-0012). The
package layering, repository-Protocol seam, and hermetic-vs-DB test split are identical to MAR.

## Data model

Three tables (one Alembic migration), per SPEC-003 + the `raw_unit` extension:

**`signals`** — `signal_id` (PK), `tenant_id`, `asset_id` (UUID, soft ref to MAR), `role`, `qudt_unit`,
`pressure_reference` (nullable), `range_min`, `range_max`, `description`, `created_at`, `deprecated_at`.
Index `(tenant_id, asset_id, role)`.

**`signal_aliases`** — `alias_id` (PK), `signal_id`, `tenant_id`, `source_system`, `raw_tag`,
**`raw_unit`**, `valid_from`, `valid_to` (NULL=active), `mapping_source`, `confidence`, `created_at`,
`confirmed_by`, `notes`. Index `(tenant_id, source_system, raw_tag)` + `(signal_id)`; **partial unique
index** on `(tenant_id, source_system, raw_tag, signal_id) WHERE valid_to IS NULL`.

> **TRS differs from MAR here:** the same `raw_tag` under a source MAY map to multiple signals at once —
> that is exactly the **ambiguous** resolution case (SPEC-003 step 1). Active uniqueness is therefore per
> *(tag, signal)*, not per *(tag)*. `find_active_aliases` returns a LIST (possibly >1), and both repos
> agree: `upsert_alias` supersedes only the prior active row for the same
> `(tenant, source, raw_tag, signal_id)`, leaving sibling signals' aliases intact.

**`signal_alias_unresolved`** — `(tenant_id, source_system, raw_tag)` PK, `first_seen_at`,
`occurrence_count`, `last_attempt_at`.

### Contract: `ResolveTagOutput` (new, in `rca_contracts`)

Mirrors `ResolveAssetOutput`: `{status: ResolveStatus, signal: SignalDescriptor | None, confidence: float,
mapping_source: str, alternatives: list[SignalDescriptor] = []}`. Provenance carried by the `ToolResponse`
envelope (same deviation-from-spec-for-consistency as MAR — the spec embedded provenance in the output).

## Resolution algorithm

`resolve_tag(repo, raw_tag, source, tenant, *, asset_hint=None, valid_at=None, min_confidence=0.85,
regex_patterns=None) -> TagResolution`:

1. **Exact**: active aliases for `(tenant, source, raw_tag)` at `valid_at`. 1 → resolved (alias confidence);
   >1 distinct signals → go to step 2 if `asset_hint` set, else **ambiguous**.
2. **Asset-hinted**: filter the step-1 candidates to those whose signal's `asset_id == asset_hint`.
   Exactly 1 → resolved (`mapping_source="asset_hinted"`); else ambiguous.
3. **Regex** (per-tenant patterns): extract a `role` named group from `raw_tag` and
   `search_signals(asset_id=asset_hint, role=role)`. Asset disambiguation uses the caller-supplied
   `asset_hint` — TRS deliberately does NOT parse an asset *tag* and resolve it to an `asset_id`, because
   asset-tag→`asset_id` is **MAR's domain** (TRS signals store `asset_id`, not asset tags); pulling that
   into TRS would couple the two services. So step 3 narrows by role (+ optional `asset_hint`); exactly 1
   match → resolved, confidence `0.70` (capped); gated by `min_confidence` (so 0.70 routes to HITL by
   default). [Reconciled with the implementation after the final review — the original "extract asset+role"
   wording implied cross-service asset-tag resolution that belongs in MAR.]
4. **No match** → `upsert_unresolved` → unresolved.

Confidence gate + cache: identical semantics to MAR (`resolved` only if `confidence >= min_confidence`;
otherwise unresolved + queued; per-tenant LRU+TTL keyed by `(tenant, source, raw_tag)`).

## Repository seam

`SignalRepository` Protocol: `find_active_aliases(tenant, source, raw_tag, *, valid_at) -> list[AliasRow]`
(returns all matches so the algorithm can detect ambiguity), `get_signal(tenant, signal_id)`,
`search_signals(tenant, *, asset_id, role, role_pattern, limit)`, `get_alias_for(signal_id, source) ->
AliasRow | None` (the reverse lookup the resolver uses), `upsert_unresolved`, `upsert_signal`,
`upsert_alias`. Two impls: `InMemoryRepository` (hermetic) + `PostgresRepository` (async; `_active`
temporal predicate mirrors the SQL exactly — the MAR parity lesson). `AliasRow` carries `raw_unit`.

## MCP surface + error boundary

Hand-wired FastMCP tools (read TRS's own repository), reusing `build_server`, `ToolResponse[T]`,
`ProvenanceAccumulator`, `map_source_error`:
- `trs.resolve_tag(ResolveTagInput) -> ToolResponse[ResolveTagOutput]`
- `trs.search_signals(SearchSignalsInput) -> ToolResponse[list[SignalDescriptor]]`
- `trs.get_signal(signal_id, tenant_id) -> ToolResponse[SignalDescriptor]`

`status` `unresolved`/`ambiguous` are successful results (data + provenance, not errors). Genuine
failures → `ToolError` via `map_source_error`; `trs.get_signal` on a missing id → `not_found`.

## Resolver wire-in (the integration deliverable)

- `TrsResolver(repo, tenant_id)` implements `SignalResolver`:
  - `resolve(signal_id)` → `repo.get_signal(tenant, signal_id)` → `SignalDescriptor`; raises
    `UnresolvedSignal` if absent.
  - `source_binding(signal_id, source)` → `repo.get_alias_for(...)` → `SourceBinding(handle=raw_tag,
    raw_unit=raw_unit)`; raises `UnresolvedSignal` if no active alias.
- **Backward-compatible** factory change to `make_pi_mcp` + `make_opcua_mcp`: add optional
  `signal_resolver: SignalResolver | None = None`; use it when provided, else build
  `InMemorySignalResolver(signals, bindings)` as today (existing tests untouched).
- **Live wire-in (OPC UA):** seed an in-memory repo → `TrsResolver` →
  `make_opcua_mcp(endpoint, namespace_uri, signal_resolver=…)` → `opc_ua.get_current_values(signal_id)`
  → real value from the OPC UA sim (NodeId handle + psig→Pa gauge via the resolved `raw_unit` + signal
  metadata). Proves the in-memory stand-in is replaced for a signal-scoped connector.

## Seeding

`packages/trs/seed_data/refplant_signals.yaml` (product-owned). Per signal: `signal_id`, `asset_id`
(matching MAR's reference assets), `role`, `qudt_unit`, `pressure_reference`, optional range; and
`aliases` per source `{raw_tag, raw_unit}`. `seed_from_register` upserts signals + one active alias per
source (`mapping_source="authoritative_import"`, confidence 1.0). The OPC UA NodeId
(`P-101A.discharge_pressure`) lines up with the sim; the PI WebID is the sim's
`"S1"+base64url(point)` value (precomputed in the register).

## Testing (MAR's hermetic-vs-DB split)

- **Hermetic (no DB):** resolution (all 4 paths incl. asset-hinted disambiguation, temporal validity,
  ambiguity, confidence gate, regex); cache; seed; the 3 MCP tools through an in-memory FastMCP client.
- **DB integration (`task trs:db`):** `PostgresRepository` vs real Postgres — CRUD, alias supersede +
  partial-unique constraint, temporal `find_active_aliases`. Skips when Postgres absent.
- **Resolver wire-in:** hermetic PI fake (TrsResolver drives `pi.get_series`); **live** OPC UA
  (`task parity:trs-wire`) drives `opc_ua.get_current_values` through TrsResolver against the real sim.

## Infra + Taskfile

- `packages/trs/pyproject.toml`: `rca-contracts`, `rca-connector-sdk`, `sqlalchemy[asyncio]>=2`,
  `alembic`, `asyncpg`, `pyyaml`, `fastmcp`.
- `infra/`: add the `rca_trs` database to the existing Postgres (an init script in
  `infra/initdb/` creating `rca_trs`, mounted into the compose's postgres).
- Taskfile: `trs:db:up`/`down` (reuse the shared postgres), `trs:migrate`, `trs:db`, `test:trs`,
  `parity:trs-wire`. Extend `lint` mypy paths with `packages/trs/src`.

## Acceptance (DoD)

1. `signals`/`signal_aliases`/`signal_alias_unresolved` migrate cleanly; partial-unique active-alias
   constraint enforced; temporal `find_active_aliases` correct.
2. Resolution passes hermetic tests across all 4 paths incl. asset-hinted disambiguation + temporal.
3. The 3 MCP tools return correct `ToolResponse[...]` (provenance present; unresolved/ambiguous are
   successes; `get_signal` miss → `not_found`).
4. Seeding populates the reference signals + per-source aliases.
5. **OPC UA connector, wired with `TrsResolver`, returns a real current value for a seeded signal from the
   sim with no static binding** — the in-memory stand-in replaced for a signal-scoped connector. PI wire-in
   verified hermetically.
6. `ruff` + `mypy` clean; existing PI/OPC UA connector tests stay green (backward-compatible factory change).

## Relationship to MAR / next

`signals.asset_id` logically references MAR's assets. With TRS landed, both resolver seams are real:
MAR backs the asset-scoped connectors (Maximo/SAP), TRS backs the signal-scoped ones (PI/OPC UA). Natural
next: a tiny composition layer / onboarding that wires both resolvers behind the connectors, then the
agent/workflow tiers (EPIC-005/006/007) that consume these MCP tools.
