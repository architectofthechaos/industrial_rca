# Sprint 2 State Report (2a + 2b)

**Date:** 2026-06-11
**Branches:** `feat/sprint-2a` (merged to `main`), `feat/sprint-2b` (ready to merge)
**Test state:** `task test` → **410 passed, 13 skipped**, ruff + mypy clean (101 source files). Skips are all live-service parity tests whose sims/brokers aren't running, plus 2 intentionally-parked MAR-wire stubs.

---

## Sprint 2a — KG, AF crawler, pattern rules, connector health (merged)

Delivered (all 12 cross-cutting acceptance items verified, see merge commit):
- **`packages/kg`** — Neo4j 5 (compose service `neo4j`), forward-only Cypher migration runner (`rca_kg.migrate`, `// @include` + `_migrations` ledger), ISO 14224 BB1 ontology (**122 nodes**) + refplant hierarchy skeleton (6 Site/Area/Unit nodes, **no Asset nodes**), and the read-only KG MCP (`make_kg_mcp`) exposing exactly four `kg.*` tools. Gateways: `Neo4jGateway` + `InMemoryGateway`.
- **Shared slug** — `rca_kg.slugs.slug` is the single definition; `rca_mar.seed._slug` re-exports it.
- **Pattern-rule registry** — `rca_mar.pattern_rules` + `seed_data/pattern_rules.yaml`; the single source of truth used by both resolution step-3 and the AF crawler (`rule:<id>` provenance; old hardcoded regex gone).
- **AF crawler** — `packages/connectors/asset_hierarchy` (`asset_hierarchy.crawl`/`crawl_subtree`), vendor_id = AF WebId, vendor_path = AF Path. Register `pi_af` aliases re-keyed to WebIds via a committed one-time script.
- **Connector health** — `rca_connector_sdk.health.register_health` adds `test_connection` + `GET /health` to all six live connectors (pi/maximo/documents/asset_hierarchy/opc_ua/mqtt); first check is the gate (fail→unhealthy, else degraded). sap_pm + echo parked.
- **Shared `ok_response`** provenance helper in the SDK (replaced three `_ok` copies).
- Phase-1 spec amended (criticality A/B/C/D, AF vendor_id=WebId, Neo4j store, Phase-1 pattern rules). `rca_platform_consolidated_context.md` does not exist — only the phase-1 spec was amended.

## Sprint 2b — Connections API, onboarding, MCP restructure, resolution queue

**Track 3 (landed first) — MCP per-entity restructure + SignalID removal:**
- `SignalID`/`SignalDescriptor` deleted; `TagDescriptor` (canonical_id + tag_name, no UUIDs) + `parse_canonical_id` + `Provenance.connection_id` added.
- SDK: `TagResolver` (was SignalResolver), `routing` (ConnectionInfo/ConnectionRouter/StaticConnectionRouter/NoActiveConnection→source_unavailable), `secrets` (SecretRef/EnvSecretResolver), `assets` (AssetGateway/StaticAssetGateway/CanonicalSlugAssetGateway), `canonical_unit_for`.
- Six entity MCP servers, entity-vocabulary tools only: `asset.*` (3), `kg.*` (4), `tag.*` (4), `work_order.*` (3), `document.*` (3), `operator_log.*` (2). Every entity response carries `provenance.connection_id`. **Zero** `pi.*`/`maximo.*`/`documents.*`/`assets.*` tool names remain (enforced by `test_no_vendor_tool_names.py`). opc_ua/uns/echo keep their names (not vendor words / parked / dev). `scripts/run_mcp_host.py` mounts all six in one process (20 tools).
- Simulator gained `/points`, `/points/{id}`, `/streams/{id}/value`, `/eventframes/{id}`.

**Track 1 — Connections API:**
- `connections` table + partial unique index `(plant_id, category) WHERE status='active'`; breaking migration 0003 replaces `asset_aliases.source_system`/`source_system_type` with a `connection_id` FK (backfilled from synth connections with a no-NULL abort assertion). `SOURCE_SYSTEM_CATEGORIES` removed.
- `packages/connections_api` FastAPI app (`/docs`): POST/GET/PATCH/DELETE/test/activate; status state machine; one-active-per-category enforced with a structured 409; `/test` calls the connector's real `test_connection`; `secret_ref` resolved at call time, never exposed (a bad ref now reports a clear test failure). Negative-trigger invariant tested.

**Track 4 — Resolution Queue write paths:**
- MAR repo `validate_binding` / `reject_binding` / `supersede_binding(system_initiated=)` (idempotent, invariant-preserving) + `/resolution_queue` endpoints (list/validate/reject/stats) in the connections_api app.

**Track 2 — Temporal onboarding pipeline:**
- Temporal dev cluster in compose (`temporal` + `temporal-ui`) + `onboarding_runs` table (migration 0004). `task infra:lite` runs PG+Neo4j only.
- `packages/onboarding` — `OnboardingWorkflow` (resolve → health(parallel) → crawl → project MAR → project KG → reconcile/decommission → coverage report), deterministic (workflow.now/uuid4, all I/O in activities), pydantic data converter, sandbox passthrough for the fastmcp/beartype import claw. FastAPI trigger/query app.
- **Verified live** against the running cluster: onboarding `refinery-gc` → 2 new + 2 updated + 6 KG nodes (the dev DB was register-seeded); idempotent re-run → all-zero counts; cmms/historian skip cleanly when their sims are down (partial coverage). Decommission, idempotency (zero-row-write via a `write_count` counter), and negative-trigger are covered hermetically.

---

## Known debt / follow-ups (flagged during reviews)

- **MAR-wire tests parked** (`test_resolver_wire_hermetic.py`, `test_mar_wire_parity.py`): the old `TagResolver`/`SourceBinding` path is gone; they need a MAR-backed `AssetGateway` adapter to be revived. Equivalent coverage exists via the entity connectors' hermetic + parity tests.
- **`test_pg_repo.py` / `test_migration_0003.py` mutate the shared dev DB** — the migration test downgrades to base and restores schema but leaves it unseeded; re-seed the refplant register before a live onboarding E2E. A `skipif` that only checks TCP reachability turns a running-but-unmigrated Postgres red; guard it when the DB layer is next touched.
- **Deprecated `AssetAliasUnresolved`** table keeps its own `source_system` PK column (out of the 0003 rename scope) — to be removed when that table is replaced (Sprint 3).
- **Onboarding `crawl_hierarchy`** uses a uniform 2-minute activity timeout and no heartbeat — fine at refplant scale (4 assets); revisit for large plants.
- **Hardcoded per-connection config** (`_SOURCE_TZ`, documents `DRIVE`) marked `TODO(track1)` — to be sourced from `ConnectionInfo.extra_config` when real auth/multi-drive lands.
- **Single-tenant** (`DEFAULT_TENANT_ID`) across the APIs and onboarding — per-request tenancy is out of Phase-1 scope.

## Out of scope (Sprint 3+), untouched
Asset nodes in KG (lazy/probe-time), LLM classifier, agent/probe/evidence/hypothesis logic, Resolution Queue UX, Vault/AWS secret providers.
