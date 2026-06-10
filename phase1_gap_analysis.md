# Phase 1 Data Layer — Gap Analysis

**Audited against:** `rca_phase1_data_layer_spec.md` (read end-to-end)
**Date:** 2026-06-10
**Scope:** Data layer only — connectors, simulators, MAR, KG ontology + hierarchy skeleton, Connections page, onboarding pipeline, MCP servers/tools. AI/agent/probe/LLM-reasoning code excluded per audit instructions.

---

## 1. Executive Summary

The codebase has built strong **foundational data services** — a MAR with resolution logic and an MCP server, seven connectors with disciplined provenance/error envelopes, and a production-grade simulator suite with deterministic seeding and cross-source coherence tests. What is almost entirely absent is the **control layer** the spec centers on: there is no knowledge graph at all, no `connections` table or Connections page, and no onboarding pipeline. In addition, a complete TRS implementation exists despite TRS being explicitly out of scope for Phase 1, and the MAR schema diverges substantially from the spec (UUID identity instead of canonical string IDs, a `parent_asset_id` hierarchy column the spec explicitly forbids, and missing resolution-workflow columns).

| Spec area | Status | One-line assessment |
|---|---|---|
| §2 MAR schema | 🟡 Partial | Tables + supersession + resolution exist, but UUID identity, forbidden hierarchy column, and ~11 missing spec columns |
| §2.3/§9 No other registries | 🔴 Violated | Full TRS signal registry implemented (`packages/trs/`) |
| §3 Knowledge Graph (ontology + skeleton) | 🔴 Missing | No graph store, no ISO 14224 ontology nodes, no Site/Unit nodes, no KG code at all |
| §4 Connections page + `connections` table | 🔴 Missing | No table, no API, no UI, no one-source-per-category enforcement, no Resolution Queue |
| §5 Onboarding pipeline | 🔴 Missing | No pipeline code; trigger discipline trivially satisfied (nothing fires), but nothing to trigger |
| §7 MCP servers + tool naming | 🟡 Partial | Servers exist per **connector** (vendor-prefixed tools), not per **entity category**; canonical IDs at boundary are respected; KG MCP and Operator Log MCP missing |
| §8.1 Connectors | 🟡 Partial | Tag/CMMS/Document connectors solid; **no Asset Hierarchy connector**; no health-check endpoints |
| §8.2–8.3 Simulators | 🟡 Partial | PI Historian, Maximo, Documents, Event Frames done; **PI AF (asset hierarchy) simulator missing** — blocks onboarding end-to-end |
| §9 Phase 1 scoping | 🔴 Violated | TRS code/infra/tasks present; no agent/probe/Temporal/fleet/on-prem code found (docs only) |

**The three biggest gaps, in order of consequence:**
1. **No KG, no Connections, no onboarding pipeline** — the entire §3–§5 control layer is unbuilt (only planned in `docs/`).
2. **MAR identity model diverges from spec** — UUIDs instead of `asset:{plant}:{unit}:{name}` canonical IDs, and hierarchy stored in the relational table (`parent_asset_id`) instead of the KG. This is load-bearing: the contracts package (`AssetID = UUID`) and every connector inherit it.
3. **No asset-hierarchy path exists at all** — no PI AF simulator, no PI AF connector, so even once a pipeline is written there is nothing for it to crawl.

---

## 2. MAR Schema

Spec reference: §2.1–§2.3. Implementation: [packages/mar/src/rca_mar/models.py](packages/mar/src/rca_mar/models.py), [packages/mar/migrations/versions/0001_initial.py](packages/mar/migrations/versions/0001_initial.py).

### 2.1 `mar_assets` vs actual `assets` table

| Spec column | Actual | Notes |
|---|---|---|
| `canonical_id` TEXT PK (`asset:{plant}:{unit}:{name}`) | ❌ `asset_id` UUID (UUIDv7) PK | Fundamental divergence — no canonical string ID anywhere ([models.py:18](packages/mar/src/rca_mar/models.py:18)) |
| `plant_id` | ❌ `tenant_id` UUID | Tenant-scoped, not plant-scoped |
| `display_name` | 🟡 `tag` | Same intent, different name ([models.py:24](packages/mar/src/rca_mar/models.py:24)) |
| `asset_class` | 🟡 `iso14224_class` + extra `iso14224_level` | Same intent, different name |
| `criticality` A/B/C | 🟡 `criticality` String(1) | Seed maps high→A; D also appears in code paths |
| `service_description` | 🟡 `service` | Same intent, different name |
| `status` (active/decommissioned/pending_review) | ❌ missing | Closest analog: `decommissioned_at` timestamp ([models.py:30](packages/mar/src/rca_mar/models.py:30)) — no `pending_review` state |
| `attributes` JSONB | ❌ missing | Class-specific fields instead promoted to typed columns (`manufacturer`, `model`, `serial_number`, `location_description`, `description`) |
| `created_at` / `updated_at` | ❌ missing | No audit timestamps on the asset row |
| **(forbidden)** hierarchy columns | ❌ **`parent_asset_id` FK present** | **Direct violation of §2.1** ("Explicitly NO parent_id / unit_id / hierarchy columns") — [models.py:20-21](packages/mar/src/rca_mar/models.py:20). The MCP tool `assets.get_hierarchy` and the seed format (`parent_unit` in [refplant_assets.yaml](packages/mar/seed_data/refplant_assets.yaml)) are built on it. |

### 2.2 `mar_asset_bindings` vs actual `asset_aliases` table

| Spec column | Actual | Notes |
|---|---|---|
| `binding_id` BIGSERIAL PK | 🟡 `alias_id` UUID PK | Different key strategy |
| `canonical_id` FK | 🟡 `asset_id` UUID FK | Follows the UUID identity model |
| `source_system_id` | 🟡 `source_system` | No separate connection-instance ID; conflates source identity with connection identity |
| `source_system_type` | ❌ missing | |
| `vendor_id` | 🟡 `external_id` | Same intent, different name |
| `vendor_path` | ❌ missing | Hierarchy path from source not captured |
| `vendor_metadata` JSONB | ❌ missing | Raw source record not retained on the binding (only `candidate_payload` JSONB on the *unresolved* table, [models.py:61](packages/mar/src/rca_mar/models.py:61)) |
| `resolution_status` (auto_resolved/pending_review/human_validated/superseded/rejected) | ❌ missing | Review workflow states are not representable; "unresolved" lives in a separate `asset_aliases_unresolved` table instead |
| `resolution_confidence` NUMERIC(4,3) | 🟡 `confidence` Float | |
| `resolution_method` (`exact_match`/`rule:<id>`/`llm_classifier_v<n>`/`manual`) | 🟡 `mapping_source` with values `authoritative_import`/`cross_walk`/`regex_heuristic`/`none` | Different vocabulary; no `rule:<id>` or LLM variants |
| `candidate_alternatives` JSONB | ❌ missing on binding | Ambiguous alternatives are returned transiently from `resolve_asset()` ([resolution.py:62-63](packages/mar/src/rca_mar/resolution.py:62)) as a bare ID list, not persisted with scores |
| `resolved_by` / `resolved_at` | ❌ missing | |
| `validated_by` / `validated_at` | 🟡 `confirmed_by` only; no timestamp | |
| `effective_from` / `effective_to` | 🟡 `valid_from` / `valid_to` | **Supersession semantics correctly implemented**: upsert closes prior active row ([repository_pg.py:45-60](packages/mar/src/rca_mar/repository_pg.py:45)) |
| Partial unique index `(source_system_id, vendor_id) WHERE effective_to IS NULL` | ✅ Equivalent: `(tenant_id, source_system, external_id) WHERE valid_to IS NULL` | [0001_initial.py](packages/mar/migrations/versions/0001_initial.py) |
| — | extra `is_primary` | Not in spec |

### 2.3 Resolution pass vs §5.3 step 3

| Spec requirement | Status | Evidence |
|---|---|---|
| Exact-match delta detection | ✅ | `find_active_alias` short-circuit, [resolution.py:45-50](packages/mar/src/rca_mar/resolution.py:45) |
| Deterministic pattern rules (e.g. `P-NNNNA` → pump class) | 🟡 | Only a regex tag-extraction heuristic (`_extract_tag`, fixed 0.70 confidence, [resolution.py:26-31](packages/mar/src/rca_mar/resolution.py:26)); no rule registry, no class assignment, no `rule:<id>` method labels |
| LLM classifier for residuals, top-3 candidates with scores | 🔴 | Not implemented anywhere in MAR |
| Auto-accept threshold, configurable, default **0.92** | 🟡 | `min_confidence` default **0.85** ([server.py:33](packages/mar/src/rca_mar/server.py:33)); crosswalk (0.85) and regex (0.70) confidences hardcoded ([resolution.py:13-14](packages/mar/src/rca_mar/resolution.py:13)); semantics differ — gates resolve/unresolve rather than auto_resolved/pending_review |
| Below threshold → `pending_review` queue | 🟡 | Goes to `asset_aliases_unresolved` occurrence-counting table instead of a reviewable binding row with alternatives |

### 2.4 Asset MCP tools vs §7.3

Actual tools ([server.py:67-114](packages/mar/src/rca_mar/server.py:67)): `assets.resolve`, `assets.get`, `assets.search`, `assets.get_hierarchy`.

| Spec tool | Status |
|---|---|
| `asset.get(canonical_id)` | 🟡 `assets.get(asset_id: UUID)` — exists but takes UUID, not canonical ID |
| `asset.find_by_vendor_id(source_system_id, vendor_id)` | 🟡 covered by `assets.resolve` (which also *creates* unresolved rows as a side effect — not a pure lookup) |
| `asset.find_by_display_name(plant_id, name)` | 🟡 approximated by `assets.search(tag_pattern, ...)` |
| `asset.list_in_unit(unit_id)` | 🔴 not exposed; `assets.get_hierarchy` walks the (spec-forbidden) relational hierarchy instead of the KG |

---

## 3. Knowledge Graph

Spec reference: §3 (ontology layer at install, Site/Unit hierarchy skeleton at onboarding, no Asset nodes, no vendor IDs in node identifiers) and §7.3 (KG MCP: `kg.get_node`, `kg.walk_hierarchy`, `kg.lookup_ontology`).

**Status: 🔴 entirely missing.** Verified by repo-wide search:

- No graph database in the stack — [infra/docker-compose.yaml](infra/docker-compose.yaml) provisions Postgres 16 only. No Neo4j/Memgrah/other graph service, no `infra/neo4j/` directory (the `README.md:75-76` tree and [docs/foundations/WEEK-1-QUICKSTART.md](docs/foundations/WEEK-1-QUICKSTART.md) *plan* a Neo4j 5.20 service + `init.cypher`, but it was never added).
- No ontology loader, no node/edge code, no `EquipmentClass`/`Subunit`/`MaintainableItem`/`FailureMode`/`FailureMechanism`/`FailureCause` node types, no `Site`/`Unit` materialization, no `belongs_to` edges.
- No KG MCP server, no `kg.*` tools.
- The only ISO 14224 presence is **string metadata**: `iso14224_class`/`iso14224_level` columns in MAR ([models.py:22-23](packages/mar/src/rca_mar/models.py:22)), the contracts `AssetDescriptor`, and simulator fixture data (e.g. failure codes in scenarios, [rca_simulator/fixtures/refplant/scenarios/](rca_simulator/fixtures/refplant/scenarios/)). None of this is a queryable ontology — there is no graph of failure modes/mechanisms/causes anywhere.
- Consequence chain: with no KG, the hierarchy had to live somewhere, which is why MAR grew the spec-forbidden `parent_asset_id` column (§2 above). Fixing the KG gap and the MAR hierarchy violation is one coupled work item.
- Identifier hygiene (§3.5) is trivially satisfied (no KG nodes exist), but note the future risk: today's only hierarchy representation keys on UUIDs and the simulator's vendor paths (`pi_af_path`), so the Site/Unit projection will need a canonical naming scheme that doesn't exist yet.

---

## 4. Connections Page and `connections` Table

Spec reference: §4 (category-first add flow, test→save with no sync, one source per category with override, `connections` table, Connections list / Entity Coverage / Resolution Queue views).

**Status: 🔴 entirely missing.**

- **No `connections` table.** The only migrations in the repo create `assets`/`asset_aliases`/`asset_aliases_unresolved` (MAR) and `signals`/`signal_aliases`/`signal_alias_unresolved` (TRS — itself out of scope). No table has `connection_id`, `category`, `connector_type`, `endpoint_config`, `auth_config`, `status`, `last_tested_at`, `last_onboarded_at`, or `last_sync_summary`.
- **No frontend of any kind** — no React/Vue/Streamlit/other UI code exists in the repo.
- **No connection-management API** — no routes for add/test/save/list connections, no category vocabulary (`asset_hierarchy`/`historian`/`cmms`/`document`/`operator_log`) encoded anywhere in implementation code.
- **No one-source-per-category enforcement** and no replacement/override/supersession-warning flow (nothing to enforce it on).
- **No Resolution Queue.** The closest analog is the `asset_aliases_unresolved` table, but it has no review actions (accept / pick alternate / reject), no `candidate_alternatives` to pick from, and no API or UI surface.
- **No Entity Coverage summary.**
- Connector configuration today is constructor/env wiring in each package's `server.py` factory plus simulator URLs — configuration as code, not as data, so there is no record the Connections page could even render.

---

## 5. Onboarding Pipeline

Spec reference: §5 (manual trigger only, preconditions, 8 steps, idempotency) and §10 criteria 3–4, 7.

**Status: 🔴 entirely missing.**

- No pipeline orchestration code exists — no "Run onboarding pipeline" action, no connection re-test step, no Asset Hierarchy crawl, no staging table, no KG projection, no connection-metadata update, no run summary. Verified by repo-wide search for onboarding/crawl/pipeline implementations; the only hits are a docstring mention in [ports.py:55](packages/connector_sdk/src/rca_connector_sdk/ports.py:55) and seed-data comments.
- **Manual-only trigger check (explicit audit item):** ✅ vacuously satisfied — there is no code path that auto-fires onboarding when a connector is added, because neither onboarding nor connector-add flows exist. There is also nothing resembling a hook/listener on connector configuration that could auto-fire later. When the pipeline is built, the manual-only constraint must be designed in (spec §5.1); nothing in the current code pre-commits the wrong direction.
- Partial building blocks that the pipeline could reuse:
  - MAR upsert with supersession ([repository_pg.py:31-66](packages/mar/src/rca_mar/repository_pg.py:31)) — covers spec step 5 mechanics.
  - `resolve_asset()` exact-match + crosswalk + regex pass ([resolution.py:34-78](packages/mar/src/rca_mar/resolution.py:34)) — a subset of spec step 3.
  - YAML seed ingestion ([seed.py](packages/mar/src/rca_mar/seed.py)) — currently the only way assets enter MAR; it plays the role onboarding should play, but from a static file rather than a crawled source.
- Note: [docs/foundations/SPEC-013-tenant-onboarding.md](docs/foundations/SPEC-013-tenant-onboarding.md) describes a *different*, larger Temporal-based tenant-onboarding workflow. It is not this spec's pipeline and is also unimplemented; treat it as superseded for Phase 1 to avoid building the wrong thing.
- Idempotency (§5.4): the alias-supersession mechanics support it, but `decommissioned`-on-removal (spec step 5, "never delete") has no implementation since there is no crawl producing removal deltas.

---

## 6. MCP Servers and Tool Naming

Spec reference: §7. Tool inventory verified directly in source.

### 6.1 Server topology — 🟡 diverges from spec

The spec mandates **one MCP server per entity category** (Asset, Tag, Work Order, Document, Operator Log, KG). The implementation has **one MCP server per connector/vendor**, built via `build_server()` + `register()` in the SDK ([mcp.py:16-37](packages/connector_sdk/src/rca_connector_sdk/mcp.py:16), [orchestrator.py:40-101](packages/connector_sdk/src/rca_connector_sdk/orchestrator.py:40)):

| Server (actual) | Tools | Spec entity category |
|---|---|---|
| MAR (`packages/mar`) | `assets.resolve`, `assets.get`, `assets.search`, `assets.get_hierarchy` | Asset MCP (closest to spec shape) |
| pi-connector | `pi.get_series`, `pi.get_summary`, `pi.get_event_frames` | Tag MCP (+ event frames) |
| opc-ua-connector | `opc_ua.get_current_values` | Tag MCP |
| echo-connector | `echo.get_series` | Tag MCP (dev artifact) |
| mqtt-connector | `uns.browse_namespace`, `uns.get_recent_messages` | Tag MCP |
| maximo-connector | `maximo.get_workorders`, `maximo.get_failure_history`, `maximo.preview_writeback`, `maximo.commit_writeback` | Work Order MCP |
| sap-pm-connector | `sap_pm.get_notifications` | Work Order MCP |
| documents-connector | `documents.search`, `documents.fetch` | Document MCP |
| — | none | Operator Log MCP 🔴 |
| — | none | KG MCP 🔴 |

### 6.2 Tool naming — 🟡 violates the hard rule

§7.2 is explicit: *"Tool names use entity vocabulary, never vendor vocabulary"* — `work_order.list_for_asset`, never `maximo_search_wo`. The implemented names `pi.get_series` ([pi/connector.py:53](packages/connectors/pi/src/rca_connector_pi/connector.py:53)), `maximo.get_workorders` ([maximo/connector.py:51](packages/connectors/maximo/src/rca_connector_maximo/connector.py:51)), `sap_pm.get_notifications`, `opc_ua.get_current_values` are vendor-prefixed and therefore violate the rule. `documents.*` and `uns.*` are closer to entity vocabulary (though spec says `document.*` / there is no `uns` entity). The consequence the spec cares about is real: swapping PI for IP.21 today would change tool names visible to callers, not just adapter config.

### 6.3 Canonical IDs at the tool boundary — ✅ (within the UUID identity model)

- Tool requests use `AssetID` / `SignalID` UUIDs ([contracts/_ids.py](packages/contracts/src/rca_contracts/_ids.py)); vendor handles (WebID, EQUNR, Maximo location, OPC NodeId) live only in resolver `SourceBinding.handle` and never surface as primary identifiers. Vendor IDs inside payloads (e.g. `WorkOrder.work_order_id`) match what §7.2 explicitly allows.
- Caveat: these are MAR/TRS UUIDs, not the spec's `asset:{plant}:{unit}:{name}` canonical strings — boundary discipline is right, ID format is not. Also, `SignalID` comes from TRS, which Phase 1 removes; per spec §7.3 tag tools should take `(canonical asset id, vendor_tag)` instead.

### 6.4 Tool catalog vs §7.3 target

| Spec tool | Status |
|---|---|
| `tag.discover_for_asset(canonical_id)` | 🔴 missing (no tag-discovery tool; TRS resolution replaced it) |
| `tag.get_history(asset_id, vendor_tag, time_range)` | 🟡 `pi.get_series(signal_id, …)` — signal-scoped, not (asset, vendor_tag)-scoped |
| `tag.get_fft(...)` | 🔴 missing (no FFT/spectrum code anywhere) |
| `work_order.list_for_asset(canonical_id, lookback)` | 🟡 `maximo.get_workorders(asset_id)` — no lookback param |
| `work_order.get(vendor_id)` | 🔴 missing |
| `work_order.search(asset_id, keywords, lookback)` | 🔴 missing (`maximo.get_failure_history` is a partial analog) |
| `document.list_for_asset(canonical_id, types?)` | 🟡 `documents.search(query)` — keyword search, not asset-scoped listing |
| `document.fetch(vendor_uri)` | ✅ `documents.fetch(document_id)` ([documents/connector.py:73](packages/connectors/documents/src/rca_connector_documents/connector.py:73)) |
| `operator_log.search(asset_id, time_range, keywords?)` | 🟡 `pi.get_event_frames` returns `Alarm`s — wrong server, wrong name, partially right data |
| `kg.get_node` / `kg.walk_hierarchy` / `kg.lookup_ontology` | 🔴 missing (no KG) |
| Asset tools | see §2.4 above |

### 6.5 What is genuinely strong here

- Every response is a `ToolResponse[T]` envelope enforcing data+provenance XOR error ([tool_response.py:25-34](packages/contracts/src/rca_contracts/tool_response.py:25)); provenance (tool name/version, source, query, record count, raw tags) is built automatically by the orchestrator. This exceeds the spec's adapter-layer requirement in spirit.
- Maximo ↔ SAP PM cross-source parity is proven by test ([packages/cross_source_tests/test_cmms_cross_source_parity.py](packages/cross_source_tests/test_cmms_cross_source_parity.py)) — both normalize to the same canonical `WorkOrder` with unified ISO 14224 failure codes.

---

## 7. Connectors and Simulators

Spec reference: §8.

### 7.1 Connectors (`packages/connectors/`)

| Spec need | Status | Notes |
|---|---|---|
| Asset Hierarchy connector (PI AF crawl + asset fetch) | 🔴 missing | No connector can crawl a hierarchy; this is the onboarding pipeline's primary input |
| Historian connector (PI) | ✅ | `pi` — series/summary/event-frames with mode semantics, unit conversion to SI |
| CMMS connector (Maximo) | ✅ | `maximo` — incl. idempotent write-back (write-back itself is beyond data-layer Phase 1 needs) |
| Document connector (SharePoint) | 🟡 | `documents` — SharePoint/Graph-*inspired* REST + S3 variant; works against the simplified simulator |
| Operator Logs connector (PI Event Frames) | 🟡 | folded into `pi.get_event_frames` → `Alarm`, not a distinct operator-log surface |
| Test/health-check endpoints (§8.1) | 🔴 missing | No connector exposes health/test-connection; the Connections page would have nothing to call. Only dev-time `_sim_reachable()` checks in parity tests |
| Vendor IDs not primary in responses | ✅ | See §6.3 |
| Beyond Phase-1 scope | — | `sap_pm` (second CMMS — only legal under Phase 1 if it *replaces* Maximo, since multi-source-per-category is excluded), `opc_ua`, `mqtt` (real-time streaming, no Phase-1 category), `echo` (SDK dev artifact). All functional and tested, none required by this spec |

### 7.2 Simulators (`rca_simulator/`) vs §8.3 coverage list

| Required simulator | Status | Evidence |
|---|---|---|
| PI AF (Asset Hierarchy) | 🔴 **missing** | [pi/app.py](rca_simulator/rca_simulator/pi/app.py) has exactly four routes: `/streams/{webId}/recorded`, `/interpolated`, `/summary`, `/eventframes` (lines 69–115). No `/assetdatabases`, `/elements`, or any hierarchy-browse endpoint. Fixtures *do* carry `pi_af_path` per asset and [plant.yaml](rca_simulator/fixtures/refplant/plant.yaml) defines a full site→area→unit→asset tree, so the data exists — only the AF API surface is missing |
| PI Historian (Tags) | ✅ | PI Web API shapes, WebID encode/decode, stored/interpolated/aggregated modes |
| Maximo (CMMS) | ✅ | OSLC surface (`oslc.where`/`oslc.select`/paging), idempotent POST |
| SharePoint (Documents) | 🟡 | [documents/app.py](rca_simulator/rca_simulator/documents/app.py) — Graph-*like* custom REST (BM25 `/search`, `/drives/{drive}/items/{id}`), explicitly simplified per SPEC-007; acceptable if the connector owns real-Graph fidelity later |
| PI Event Frames (Operator Logs) | 🟡 | `/eventframes` returns scenario alarms; not the full AF event-frame model (no asset-scoped frames) |

Extras beyond Phase 1: OPC UA (real `asyncua` server mirroring the plant hierarchy as folders), MQTT Sparkplug B (real broker, Tahu-conformant protobuf), SAP PM (OData v2 with CSRF dance). All high quality; none required.

Spec qualities that **pass**: deterministic seeding everywhere (SHA-256-derived `random.Random`, no salted `hash()`) — [scenario_expander.py:59-65](rca_simulator/rca_simulator/fixtures/scenario_expander.py:59), [realism/inject.py:20-23](rca_simulator/rca_simulator/realism/inject.py:20); vendor-protocol fidelity for PI/Maximo/SAP/OPC UA/MQTT; cross-source timeline coherence proven by [test_cross_source_coherence.py](rca_simulator/tests/test_cross_source_coherence.py); fixture validation enforced at simulator startup ([fixtures/_validate.py:64-143](rca_simulator/rca_simulator/fixtures/_validate.py:64)).

---

## 8. Phase 1 Scoping Violations (paths only)

**TRS — implementation code (spec §2.3, §9: explicitly excluded):**
- `packages/trs/src/rca_trs/__init__.py`
- `packages/trs/src/rca_trs/config.py`
- `packages/trs/src/rca_trs/models.py`
- `packages/trs/src/rca_trs/repository.py`
- `packages/trs/src/rca_trs/repository_pg.py`
- `packages/trs/src/rca_trs/resolution.py`
- `packages/trs/src/rca_trs/resolver.py`
- `packages/trs/src/rca_trs/server.py`
- `packages/trs/src/rca_trs/cache.py`
- `packages/trs/src/rca_trs/seed.py`
- `packages/trs/seed_data/refplant_signals.yaml`
- `packages/trs/migrations/env.py`
- `packages/trs/migrations/versions/0001_initial.py`
- `packages/trs/tests/` (10 test modules)
- `packages/trs/pyproject.toml`

**TRS — infra / build wiring:**
- `infra/initdb/01-create-trs-db.sql`
- `pyproject.toml` (workspace member `"packages/trs"`, line 5)
- `Taskfile.yaml` (tasks `trs:db:up`, `trs:db:down`, `trs:migrate`, `trs:db`, `test:trs`, `parity:trs-wire`, lines 132–165)

**TRS — docs only (keepable, flag as deferred):**
- `docs/trs/` (4 files), `docs/superpowers/plans/2026-06-06-trs.md`, `docs/superpowers/specs/2026-06-06-trs-design.md`, `docs/adrs/0001-tag-resolution-service.md`

**Work-order / document / log registries:** none found ✅
**Multi-source-per-category logic:** none found ✅ (note: `sap_pm` + `maximo` both targeting CMMS is a latent multi-source posture, but no binding logic exists yet)
**Probe / agent / LLM-reasoning / Temporal / fleet / on-prem code:** none found ✅ — docs only (`docs/agents/`, `docs/temporal/`, `docs/adrs/0003`, `docs/adrs/0004`)

Removal impact: no Python module outside `packages/trs` imports `rca_trs` (verified by grep) — but the spec's replacement design matters: §7.3 expects `tag.discover_for_asset` / `tag.get_history(asset_id, vendor_tag, …)` instead of TRS signal resolution, so connectors currently typed on `SignalID` ([contracts/_ids.py](packages/contracts/src/rca_contracts/_ids.py), [connector_sdk/ports.py](packages/connector_sdk/src/rca_connector_sdk/ports.py)) need re-plumbing, not just deletion.

---

## 9. Cross-Cutting Issues

1. **Identifier hygiene — single biggest systemic divergence.** The spec's identity model is canonical TEXT IDs (`asset:{plant}:{unit}:{name}`) minted by MAR, with `plant_id` scoping. The implementation standardized on UUIDv7 + `tenant_id` across MAR, TRS, contracts, and every connector. Neither is wrong in isolation, but they are incompatible, and the choice propagates everywhere (`AssetID`/`SignalID`/`TenantID` in contracts; fixture `asset_id_seed`s; tool request models). This must be decided explicitly before any other schema work — either amend the spec or migrate the code.
2. **Naming drift.** Tables (`assets` vs `mar_assets`, `asset_aliases` vs `mar_asset_bindings`), columns (`external_id`/`vendor_id`, `valid_*`/`effective_*`, `mapping_source`/`resolution_method`, `confidence`/`resolution_confidence`), tool prefixes (vendor vs entity), and vocabulary (`alias` vs `binding`) all diverge from the spec consistently. Internal docs (SPEC-011) match the code, not the Phase-1 spec — the two spec lineages need reconciliation.
3. **Resolution semantics drift.** Spec models review state *on the binding row* (`resolution_status` + `candidate_alternatives`); code models it as a *separate unresolved table* with occurrence counting. The spec's Resolution Queue (accept / pick alternate / reject) cannot be built on the current shape without schema change.
4. **Test coverage** is genuinely good for what exists: MAR (resolution, temporal aliases, repo parity in-memory↔Postgres, MCP envelope, cache, seed), connectors (hermetic + live parity per connector + CMMS cross-source), simulators (128 tests + 6/6 end-to-end smoke). Zero coverage for everything missing (KG, connections, onboarding) — and no test asserts the spec's headline invariants (no Asset nodes in KG, onboarding manual-only, one-source-per-category).
5. **Dead/dev code.** `echo` connector is an SDK dev artifact (fine, but mark it non-product); MAR's `cache.py` `ResolutionCache` is built and tested but wired into nothing; `MarResolver.resolve()` is an intentional stub raising `UnresolvedSignal` ([resolver.py:22-24](packages/mar/src/rca_mar/resolver.py:22)); `README.md` documents an `infra/neo4j/` directory that doesn't exist.
6. **Config-as-code.** Connector endpoints/auth are constructor wiring, with no secrets-store indirection (`auth_config` referencing a secret, §4.4). Fine for sims, but the connections work must introduce config-as-data without leaving two sources of truth.

---

## 10. Recommended Work Plan

Ordered by dependency; each item lists spec reference, type, effort (S/M/L), dependencies, risk.

| # | Item | Spec | Type | Effort | Depends on | Risk |
|---|---|---|---|---|---|---|
| 1 | **Decide identity model**: canonical TEXT IDs per spec vs amend spec to bless UUIDs (recommendation: keep UUID PKs internally, add spec-format `canonical_id` TEXT as the unique, tool-boundary identifier) | §2.1, §11 | decision | S | — | High if skipped — every later item builds on it |
| 2 | **Remove TRS** from Phase 1: drop `packages/trs`, workspace member, Taskfile tasks, `01-create-trs-db.sql`; mark docs deferred | §9 | remove | S | — | Low for deletion itself; Medium overall because item 9 must replace `SignalID` plumbing in connectors |
| 3 | **MAR schema alignment**: add `canonical_id`, `status`, `attributes`, `created_at`/`updated_at`; add binding columns (`source_system_type`, `vendor_path`, `vendor_metadata`, `resolution_status`, `candidate_alternatives`, `resolved_by/at`, `validated_at`); **drop `parent_asset_id`** (hierarchy moves to KG, item 6); rename to spec vocabulary or document the mapping | §2.1–2.2 | modify | L | 1 | High — touches contracts, seed format, `assets.get_hierarchy` (which must be removed/re-pointed at KG), and all MAR tests |
| 4 | **PI AF simulator**: add `/assetdatabases` + `/elements` hierarchy-browse endpoints to [pi/app.py](rca_simulator/rca_simulator/pi/app.py), serving the tree already in `plant.yaml` + `pi_af_path` fixtures | §8.3 | add | M | — | Low — data already exists; parallelizable with 3 |
| 5 | **Asset Hierarchy (PI AF) connector** + `connections` table & API: crawl interface for onboarding, `connections` schema per §4.4, add/test/save endpoints, one-source-per-category enforcement with override | §4.3–4.4, §8.1 | add | L | 4 (sim to test against), 1 | Medium — new surface area; keep auth as secret references from day one |
| 6 | **KG foundation**: provision graph store in [infra/docker-compose.yaml](infra/docker-compose.yaml); ISO 14224 BB1 ontology loader (~120 nodes, install-time); `Site` node on plant creation; `Unit` upsert + `belongs_to` edges API for the pipeline; enforce no-vendor-ID node identifiers | §3 | add | L | 1 | Medium — greenfield; ontology content authoring is the long pole |
| 7 | **Onboarding pipeline**: manual-trigger-only endpoint implementing §5.3 steps 1–8 (re-test → crawl → resolution → KG skeleton projection → MAR upsert/supersede/decommission → queue reviews → connection metadata → summary); idempotency tests; an explicit test that connector-add does NOT trigger it | §5, §10.3–4,7 | add | L | 3, 5, 6 | Medium — mechanics exist in MAR repo layer; orchestration is new |
| 8 | **Resolution pass upgrades**: deterministic pattern-rule registry (`rule:<id>` methods), LLM classifier with top-3 scored `candidate_alternatives`, configurable auto-accept threshold defaulting 0.92, statuses written to `resolution_status` | §5.3 step 3 | modify | M | 3 | Medium — LLM classifier needs eval data; thresholds configurable, not hardcoded |
| 9 | **MCP restructure to per-entity servers + entity tool names**: `tag.*` (PI adapter; `discover_for_asset`, `get_history(asset_id, vendor_tag, …)` replacing SignalID plumbing), `work_order.*` (Maximo adapter; add `get(vendor_id)`, `search`, `lookback`), `document.*` (`list_for_asset`), `operator_log.search` (PI Event Frames adapter), `asset.*` rename + add `find_by_vendor_id`/`find_by_display_name`/`list_in_unit` | §7.1–7.3 | modify | L | 1, 2, 3 | High — renames every tool and request model; mitigated by existing parity tests; do once, not incrementally |
| 10 | **KG MCP server**: `kg.get_node`, `kg.walk_hierarchy`, `kg.lookup_ontology` (read-only) | §7.3 | add | M | 6 | Low |
| 11 | **Connector health-check endpoints** consumed by connection test/save and pipeline step 1 | §8.1, §5.3.1 | add | S | 5 | Low |
| 12 | **Connections page UI**: category-first add flow, connections list, Entity Coverage summary, "Run onboarding pipeline" action with run summary, Resolution Queue (accept / alternate / reject) | §4.1–4.5 | add | L | 5, 7, 8 | Medium — first frontend in the repo; stack choice needed |
| 13 | **Park out-of-category connectors** (`opc_ua`, `mqtt`, `sap_pm`, `echo`): exclude from default workspace/test runs or clearly mark non-Phase-1; decide Maximo-vs-SAP as the single CMMS source | §1.2, §9 | modify | S | — | Low — keep code, remove from the Phase-1 critical path |
| 14 | **Spec-invariant test suite**: assert no Asset nodes in KG post-onboarding, no vendor IDs in KG identifiers, one-active-binding index behavior, manual-only trigger, idempotent re-runs (§10 criteria as executable checks) | §10 | add | M | 7 | Low — high leverage for keeping later phases honest |

**Sequencing summary:** 1 → (2, 3, 4 in parallel) → (5, 6 in parallel) → 7 → (8, 9, 10, 11 in parallel) → 12 → 13/14 anytime after their dependencies.

---

*Method note: spec read end-to-end; codebase audited via parallel read-only exploration of `packages/mar`, `packages/trs`, `packages/connectors/*`, `packages/connector_sdk`, `packages/contracts`, `rca_simulator`, `infra`, and `docs`; all load-bearing claims (schema columns, tool names, simulator routes, absence of KG/connections/onboarding code) verified directly against source. No code was modified.*
