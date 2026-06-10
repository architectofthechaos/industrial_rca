# EPIC-012: Master Asset Registry

**Goal**: Implement MAR per [SPEC-011](SPEC-011-master-asset-registry.md) — canonical asset identity, hierarchy, ingestion paths, and unresolved queue.

**Duration**: Week 2–3 (Phase 2, before TRS)

**Dependency**: EPIC-001 Foundations (contracts, Postgres, docker-compose).

## MVP build status (2026-06-06)

First MVP slice built — see `MAR-BUILD-NOTES.md` (+ spec/plan under `docs/superpowers/`).
- ✅ **S12.1 Storage** (assets/aliases/unresolved, SQLAlchemy 2.0 async + Alembic, partial-unique active alias).
- ✅ **S12.2 Resolution** (4-step + confidence gate + LRU/TTL cache, behind a repository Protocol).
- ✅ **S12.3 MCP server** (`assets.resolve`/`get`/`search`; `get_hierarchy` removed Sprint 1 — hierarchy moves to the KG in Sprint 2).
- 🟡 **S12.4 (authoritative ingestion)** — done via a **product-owned YAML register seed** (the sims expose
  no asset-discovery endpoints, so live Maximo/PI-AF/UNS import — S12.4–S12.6 — is deferred until the sims grow them).
- ➕ Beyond the stories: in-process `MarResolver` wired into the Maximo + SAP PM connectors (replaces the
  in-memory stand-in for asset-scoped connectors; signal-level binding waits for TRS).
- ⬜ Deferred: S12.5/6 (live cross-walk), S12.7 spreadsheet importer, S12.8 SAP-authoritative toggle,
  S12.9 unresolved-queue UI, S12.10 merge tool, S12.11 runbook.

## Stories

### S12.1 — Storage layer
- Postgres tables (`assets`, `asset_aliases`, `asset_aliases_unresolved`).
- Alembic migrations.
- DAO with strict typed interfaces, supports hierarchy recursive queries.

**DoD**: Unit-tested CRUD; recursive hierarchy fetch works; unique-active-alias constraint enforced.

### S12.2 — Resolution algorithm
- 4-step resolution (exact, cross-walk, regex, unresolved).
- Configurable per-tenant regex patterns.
- In-process LRU cache.

**DoD**: Unit tests cover all 4 paths including temporal validity edge cases; p50 < 5ms.

### S12.3 — MCP server
- FastMCP server exposing `assets.resolve`, `assets.get`, `assets.search`, `assets.classify_iso14224`, `assets.register`, `assets.confirm_alias`, `assets.merge`; `assets.get_hierarchy` removed Sprint 1 — hierarchy moves to the KG in Sprint 2.

**DoD**: Contract tests pass; tool list matches SPEC-011.

### S12.4 — Maximo ingestion (authoritative)
- Pulls functional location hierarchy.
- Pulls equipment master.
- Creates assets with primary aliases on Maximo source.
- ISO 14224 class derived from Maximo equipment classification + tenant mapping.

**DoD**: Reference plant (4 pumps + hierarchy) fully populated from Maximo simulator.

### S12.5 — PI AF cross-walk
- Walks PI AF elements.
- Matches to existing assets by tag.
- Creates aliases; unmatched go to unresolved queue.

**DoD**: All reference-plant PI AF elements match to existing assets.

### S12.6 — UNS cross-walk
- Parses UNS namespace from Sparkplug BIRTH messages.
- Matches asset segment to existing assets.
- Creates aliases.

**DoD**: UNS-published assets resolve to existing asset_ids.

### S12.7 — Spreadsheet import path
- CSV/Excel importer for engineering tag register.
- Schema validation, dry-run mode, diff against existing assets.

**DoD**: Importer round-trips a fixture spreadsheet without data loss.

### S12.8 — SAP PM ingestion
- Same shape as Maximo (functional locations + equipment master).
- Configurable per-tenant whether Maximo or SAP is authoritative.

**DoD**: Tenant can switch authoritative source via config.

### S12.9 — Unresolved-asset queue + UI stub
- API endpoints for queue listing and confirmation.
- Minimal admin UI page (consistent with EPIC-008 HITL UI stack).

**DoD**: Unresolved asset from a cross-walk surfaces in queue and can be confirmed.

### S12.10 — Asset merge tool
- `assets.merge` admin tool.
- Reassigns dependent rows (aliases, signals).
- 7-day soft-undo window.

**DoD**: Accidental duplicate detected by a cross-walk can be merged and undone.

### S12.11 — Onboarding runbook
- Documented onboarding sequence per SPEC-011.
- Per-tenant configuration template.
- Acceptance checklist before TRS ingestion begins.

**DoD**: Runbook reviewed; reference plant fully onboards end-to-end in < 30 minutes from scratch.

## Out of scope

- MAR write-back to source systems (one-way only for MVP).
- Bulk reclassification UI (admin can do via API/SQL for MVP).
