# EPIC-003: Tag Resolution Service

**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

**Goal**: Implement TRS per [SPEC-003](SPEC-003-tag-resolution-service.md) with ingestion paths and the unresolved-tag queue.

**Duration**: Week 3–4

**Depends on**: [EPIC-012 Master Asset Registry](EPIC-012-master-asset-registry.md). MAR must be populated before TRS ingestion runs.

## MVP build status (2026-06-06)

First MVP slice built — see `TRS-BUILD-NOTES.md` (+ spec/plan under `docs/superpowers/`).
- ✅ **S3.1 Storage** (signals/aliases/unresolved, SQLAlchemy 2.0 async + Alembic; `raw_unit` added;
  partial-unique active alias per `(tenant, source, raw_tag, signal_id)` — TRS allows the same tag on
  multiple signals = the ambiguous case).
- ✅ **S3.2 Resolution** (4-step: exact → asset-hinted → regex → unresolved; confidence gate; LRU/TTL cache).
- ✅ **S3.3 MCP server** (`trs.resolve_tag` / `trs.search_signals` / `trs.get_signal`).
- 🟡 **S3.4 (ingestion)** — done via a **product-owned YAML register seed** (sims expose no catalog
  endpoints, so live UNS/PI-AF/Maximo ingestion is deferred until the sims grow them).
- ➕ Beyond the stories: in-process `TrsResolver` (full SignalResolver) wired into the PI + OPC UA
  connectors — replaces the in-memory stand-in for the signal-scoped connectors (live OPC UA wire-in
  parity green; PI hermetic). Both resolver seams (MAR assets + TRS signals) are now real.
- ⬜ Deferred: S3.5 unresolved-queue UI + `register_signal`/`confirm_alias`, S3.6 bulk-resolve API, live ingestion.

Database: TRS uses its own `rca_trs` DB on the shared Postgres; `signals.asset_id` is a soft reference
to MAR (no hard cross-DB FK) — flagged in the build notes.

## Stories

### S3.1 — Storage layer
- Postgres tables (`signals`, `signal_aliases`, `signal_alias_unresolved`).
- DAO with strict typed interfaces.

**DoD**: Unit-tested CRUD with temporal validity edge cases.

### S3.2 — Resolution algorithm
- 4-step resolution (exact, asset-hinted, regex, unresolved).
- Configurable per-tenant regex patterns.
- In-process LRU cache.

**DoD**: Unit tests cover all paths; p50 < 5ms.

### S3.3 — MCP server
- FastMCP server exposing `trs.resolve_tag`, `trs.search_signals`, `trs.get_signal`, `trs.register_signal`, `trs.confirm_alias`.

**DoD**: Contract tests pass.

### S3.4 — Ingestion paths
- UNS ingestor (consumes Sparkplug BIRTH from MQTT simulator).
- PI AF browse ingestor (consumes PI simulator metadata).
- Maximo asset import.
- Regex onboarding tool.

**DoD**: Reference plant fully populated in TRS by running ingestors against simulators.

### S3.5 — Unresolved-tag queue + UI stub
- API endpoints for queue listing and confirmation.
- Minimal admin UI page (HTMX or React, scope dependent on EPIC-008).

**DoD**: An unresolved tag from a probe surfaces in the queue and can be confirmed.

### S3.6 — Caching and performance
- LRU cache with 60s TTL per tenant.
- Bulk resolve API for evidence-tier fan-out.

**DoD**: 100 concurrent resolves complete in < 200ms.
