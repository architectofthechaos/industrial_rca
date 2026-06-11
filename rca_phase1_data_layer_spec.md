# RCA Platform — Phase 1 Data Layer Specification

**Scope:** Connectors, data model, MAR (Master Asset Registry), KG schema and population strategy, Connections page, onboarding data pipeline, MCP servers and tools, simulators.

**Out of scope for this spec:** AI agents, probe orchestration, RCA reasoning flows, model selection, LLM prompting. Probe-time behavior is mentioned only where it constrains the data-layer design.

**Out of scope for Phase 1 entirely:** TRS (Tag Resolution Service), work-order/document/log canonical registries, multi-source-per-category support, fleet pattern detection across plants, on-prem deployments.

---

## 1. Design Principles

1. **Data model first.** The platform reasons about canonical entities (Asset, Tag, Work Order, Document, Operator Log). Connectors are data sources bound to those entities, not the data model itself. User-facing language always uses the entity/category vocabulary, never vendor names.
2. **One source per entity category per plant (Phase 1 constraint).** A plant has exactly one bound source for Asset Hierarchy, one for Historian, one for CMMS, one for Documents, one for Operator Logs. This makes vendor IDs unambiguous within a category and eliminates the need for cross-source canonical IDs on transient entities.
3. **Canonical IDs only for assets.** Assets are referenced repeatedly across the platform's lifetime. They get canonical IDs and a registry (MAR). Tags, work orders, documents, and logs are referenced by `(source_system_id, vendor_id)` and never registered.
4. **KG is the reasoning/relationship layer; MAR is the identity layer.** MAR is flat relational (Postgres). All hierarchy and ontology relationships live in the KG. The KG holds no parent/child columns; MAR holds no edges.
5. **KG plant-instance layer is built lazily** (outside the scope of this spec — see §6). At onboarding, only the ontology layer and the hierarchy skeleton (Site + Unit nodes) are materialized. No Asset nodes are created at onboarding.
6. **Onboarding is manually triggered.** The onboarding pipeline never auto-fires when a connector is added. The user clicks an explicit "Run onboarding pipeline" action when they have wired up the sources they intend to bind. Re-runs are idempotent and allowed.

---

## 2. MAR — Master Asset Registry

### 2.1 `mar_assets` (canonical assets — flat table, no hierarchy columns)

| Column                | Type        | Notes                                                                       |
| --------------------- | ----------- | --------------------------------------------------------------------------- |
| `canonical_id`        | TEXT PK     | e.g. `asset:refinery-gc:cdu:p-2103a`                                        |
| `plant_id`            | TEXT        | Plant scope                                                                 |
| `display_name`        | TEXT        | Human-readable equipment tag, e.g. `P-2103A`                                |
| `asset_class`         | TEXT        | Links to ISO 14224 ontology, e.g. `centrifugal-pump-bb1`                    |
| `criticality`         | TEXT        | `A` / `B` / `C` / `D`                                                       |
| `service_description` | TEXT        | Free text                                                                   |
| `status`              | TEXT        | `active` / `decommissioned` / `pending_review`                              |
| `attributes`          | JSONB       | Class-specific fields (rated_flow, rated_head, materials, etc.)             |
| `created_at`          | TIMESTAMPTZ |                                                                             |
| `updated_at`          | TIMESTAMPTZ |                                                                             |

**Explicitly NO `parent_id` / `unit_id` / hierarchy columns.** Hierarchy lives in the KG only.

### 2.2 `mar_asset_bindings` (vendor → canonical mapping)

| Column                  | Type          | Notes                                                          |
| ----------------------- | ------------- | -------------------------------------------------------------- |
| `binding_id`            | BIGSERIAL PK  |                                                                |
| `canonical_id`          | TEXT FK       | → `mar_assets.canonical_id`                                    |
| `source_system_id`      | TEXT          | Configured connection, e.g. `refinery-gc.pi-af.prod`           |
| `source_system_type`    | TEXT          | `pi_af` / `sap_cmdb` / `csv` / `json`                          |
| `vendor_id`             | TEXT          | Raw asset ID in the source. For PI AF sources, `vendor_id` is the AF **WebId** and `vendor_path` is the AF **Path** (Sprint 2a decision; WebIds are stable across path renames). |
| `vendor_path`           | TEXT          | Hierarchy path in source (e.g. `\Site\Unit21\CDU\P-2103A`)     |
| `vendor_metadata`       | JSONB         | Raw record blob from source                                    |
| `resolution_status`     | TEXT          | `auto_resolved` / `pending_review` / `human_validated` / `superseded` / `rejected` |
| `resolution_confidence` | NUMERIC(4,3)  | 0.000–1.000                                                    |
| `resolution_method`     | TEXT          | `exact_match` / `rule:<id>` / `llm_classifier_v<n>` / `manual` |
| `candidate_alternatives`| JSONB         | Other canonical-ID candidates with scores                      |
| `resolved_by`           | TEXT          | Agent name or user email                                       |
| `resolved_at`           | TIMESTAMPTZ   |                                                                |
| `validated_by`          | TEXT          |                                                                |
| `validated_at`          | TIMESTAMPTZ   |                                                                |
| `effective_from`        | TIMESTAMPTZ   |                                                                |
| `effective_to`          | TIMESTAMPTZ   | NULL = currently active                                        |
| `notes`                 | TEXT          |                                                                |

**Partial unique index:** `(source_system_id, vendor_id) WHERE effective_to IS NULL` — at most one active binding per vendor ID per source.

### 2.3 No other registries in Phase 1

- ❌ No `trs_tags` / `trs_tag_bindings`
- ❌ No work-order registry
- ❌ No document registry
- ❌ No operator-log registry

Tags, work orders, documents, and logs are accessed via MCP tool calls to their bound source at the moment they're needed.

---

## 3. Knowledge Graph

**Store:** Neo4j 5.x Community (dev mode in the product `docker-compose.yaml`).

### 3.1 Layers

- **Ontology layer** — pre-loaded at platform install. ISO 14224 catalog: Equipment Class, Subunit, Maintainable Item, Failure Mode, Failure Mechanism, Failure Cause. **Phase 1 scope: centrifugal pumps (BB1) only**, ~120 nodes.
- **Hierarchy skeleton** — materialized at onboarding. `Site` and `Unit` nodes for the plant. **No Asset nodes.**
- **Plant-instance layer** — out of scope for this spec. Asset and tag nodes are materialized later, at probe time, by the agent layer.

### 3.2 KG state at each lifecycle event

| Lifecycle event                        | KG state                                                                                  |
| -------------------------------------- | ----------------------------------------------------------------------------------------- |
| Platform install                       | ISO 14224 ontology nodes loaded                                                           |
| Plant created                          | One `Site` node                                                                           |
| Connections added (any category)       | **No KG changes.** Connections are configuration only.                                    |
| **User clicks "Run onboarding"**       | Crawls bound Asset Hierarchy source. Materializes `Unit` nodes under the `Site`. Populates MAR. **No Asset nodes created.** |
| Re-runs of "Run onboarding"            | Idempotent. Deltas applied to MAR. New `Unit` nodes added if discovered.                  |

**Asset and Tag nodes are out of scope for this spec.** They are materialized at probe time by the agent layer (future work).

### 3.3 Node types created in Phase 1

| Node type           | Created at            | Notes                                  |
| ------------------- | --------------------- | -------------------------------------- |
| `EquipmentClass`    | Platform install      | ISO 14224                              |
| `Subunit`           | Platform install      | ISO 14224                              |
| `MaintainableItem`  | Platform install      | ISO 14224                              |
| `FailureMode`       | Platform install      | ISO 14224                              |
| `FailureMechanism`  | Platform install      | ISO 14224                              |
| `FailureCause`      | Platform install      | ISO 14224                              |
| `Site`              | Plant creation        | One per plant                          |
| `Unit`              | Run onboarding action | Materialized from Asset Hierarchy crawl|

### 3.4 Edge types in Phase 1

- `Unit --belongs_to--> Site`
- Ontology edges between ISO 14224 nodes (Class → Subunit → MaintainableItem → FailureMode → FailureMechanism → FailureCause)

Edges that touch Asset or Tag nodes are out of scope for this spec — they will be added when the agent layer materializes those nodes at probe time.

### 3.5 Identifier hygiene rule

**KG nodes are identified only by canonical IDs or ontology IDs. Vendor IDs never appear in KG node identifiers or primary properties.** Vendor IDs live exclusively in MAR (and, for tags/work-orders/docs/logs, will live in the agent-layer evidence records — outside this spec).

---

## 4. Connections Page

### 4.1 User flow

**Step 1 — Pick category** (user-friendly vocabulary, mapped 1:1 to data-model entities):

| Category                  | Maps to entity    | Phase 1 status                        |
| ------------------------- | ----------------- | ------------------------------------- |
| Asset Hierarchy           | Asset, Site, Unit | ✅ Required for any onboarding        |
| Historian / Time-Series   | Tag (at probe time) | ✅ Optional                         |
| CMMS / Work Management    | Work Order        | ✅ Optional                           |
| Document Repository       | Document          | ✅ Optional                           |
| Operator Logs / Events    | Operator Log      | ✅ Optional                           |
| Reference Data / Standards| Reference Data    | Built-in (ISO 14224 pre-loaded)       |

**Step 2 — Pick connector** within that category. UI lists available connectors filtered by category (e.g. for Asset Hierarchy: PI AF / SAP CMDB / CSV upload / JSON / custom REST).

**Step 3 — Enter connection details** (endpoint, auth, optional path filters).

**Step 4 — Test → Save.** The connection is now configured. **No data sync happens here.** Saving stores the config and verifies the platform can reach the source.

### 4.2 Onboarding action (manual trigger)

The Connections page exposes a primary action: **"Run onboarding pipeline."**

- Enabled whenever at least one **Asset Hierarchy** connection is bound and tested.
- Always available for re-runs after the first execution (idempotent).
- **Onboarding is never triggered automatically when a connector is added.** The user is in control of when the pipeline runs.
- It is acceptable and expected for the user to click "Run onboarding" with partial coverage (e.g., only Asset Hierarchy bound, no CMMS yet). The pipeline handles partial coverage gracefully.

After a run, the UI displays a coverage summary: which categories are bound, how many assets were registered, how many bindings are awaiting review.

### 4.3 Phase 1 constraints

- One bound source per category per plant. The "+ Add connection" flow blocks adding a second connector to a category that already has one (with override option requiring explicit confirmation, for the rare case of replacement).
- Replacing a connector within a category is allowed but warns about supersession effects on existing MAR bindings.

### 4.4 `connections` table

| Column                | Type          | Notes                                                            |
| --------------------- | ------------- | ---------------------------------------------------------------- |
| `connection_id`       | TEXT PK       | e.g. `refinery-gc.pi-af.prod`                                    |
| `plant_id`            | TEXT          |                                                                  |
| `category`            | TEXT          | `asset_hierarchy` / `historian` / `cmms` / `document` / `operator_log` |
| `connector_type`      | TEXT          | `pi_af` / `pi_historian` / `maximo` / `sap_pm` / `sharepoint` / etc. |
| `endpoint_config`     | JSONB         | URL, paths, filters                                              |
| `auth_config`         | JSONB         | Reference to a secret in the secrets store (not the secret itself) |
| `status`              | TEXT          | `connected` / `auth_failed` / `unreachable` / `disabled`         |
| `last_tested_at`      | TIMESTAMPTZ   | When connection was last verified reachable                      |
| `last_onboarded_at`   | TIMESTAMPTZ   | When this connection was last included in an onboarding run     |
| `last_sync_summary`   | JSONB         | e.g. `{"assets_discovered": 470, "bindings_pending_review": 12}` |
| `created_at`          | TIMESTAMPTZ   |                                                                  |
| `updated_at`          | TIMESTAMPTZ   |                                                                  |

### 4.5 Required views

- **Connections list** — current state of every connection, grouped by category, with status indicators.
- **Entity Coverage summary** — which categories are bound vs. unbound, in category vocabulary, not entity vocabulary.
- **Resolution Queue** — MAR bindings with `resolution_status = 'pending_review'`. User accepts, picks an alternate from `candidate_alternatives`, or rejects. Each action updates the binding row.

---

## 5. Onboarding Data Pipeline

### 5.1 Trigger

**Explicit user action only.** The user clicks "Run onboarding pipeline" on the Connections page. The pipeline never fires automatically when a connector is added or modified.

### 5.2 Preconditions

- At least one Asset Hierarchy connection exists with `status = 'connected'`.
- (No other category is required. Onboarding with partial coverage is supported.)

### 5.3 Steps

1. **Re-test bound connections.** Verify the Asset Hierarchy source is reachable. Refresh `status` and `last_tested_at` on the connection row. Abort cleanly with a user-facing error if unreachable.
2. **Crawl the Asset Hierarchy source.** Walk the full hierarchy (PI AF traversal / CSV parse / JSON load / etc.). Load all asset records and the hierarchy path of each into a staging table.
3. **Resolution pass on assets:**
   - **Exact-match rules** — vendor IDs that already match an existing `mar_asset_bindings` row pass through as no-ops (delta detection).
   - **Deterministic pattern rules** — e.g., `P-NNNNA` → centrifugal pump class — produce high-confidence canonical-ID proposals. Pattern rules ship in Phase 1 as a versioned rule registry (`packages/mar/seed_data/pattern_rules.yaml`); provenance is written as `rule:<id>`. (Amended in Sprint 2a — previously implied as deferred.)
   - **LLM classifier** for residuals — proposes `canonical_id` and `asset_class` against the ISO 14224 ontology, returns top-3 candidates with confidence scores.
   - **Auto-accept threshold** — configurable, default 0.92. Rows above threshold get `resolution_status = 'auto_resolved'`.
   - **Below threshold** → `resolution_status = 'pending_review'`, queued for human review.
4. **Project hierarchy skeleton into KG.** From the discovered hierarchy paths, create or upsert `Site` (one per plant) and `Unit` nodes with `Unit --belongs_to--> Site` edges. **Do NOT create Asset nodes.**
5. **Insert / update MAR rows.**
   - New canonical assets → insert into `mar_assets`.
   - New bindings → insert into `mar_asset_bindings`.
   - Changed bindings → set old row's `effective_to = now()`, insert new row.
   - Removed assets in source → set `mar_assets.status = 'decommissioned'` (never delete).
6. **Surface pending reviews** in the Resolution Queue.
7. **Update connection metadata.** Set `last_onboarded_at` and `last_sync_summary` on each connection that participated.
8. **Return a summary** to the UI: assets registered, units added to KG, bindings pending review, coverage state across categories.

### 5.4 Idempotency

- Multiple runs on the same source produce only deltas.
- Re-runs never delete; they supersede with `effective_to`.
- Adding a new connector and re-running picks up that new source without disturbing already-onboarded ones.

### 5.5 What the pipeline does NOT do in Phase 1

- ❌ Does not query the Historian, CMMS, Document, or Operator Log connectors. Those are read at probe time by the agent layer (out of scope).
- ❌ Does not create Asset or Tag nodes in the KG.
- ❌ Does not pre-fetch any historical data (work orders, documents, logs). Those are pulled on demand later.

---

## 6. Probe-Time Behavior (informational — out of scope for this spec)

This is mentioned only so engineering understands why the data layer is shaped the way it is. **No probe orchestration code is being designed or built as part of this spec.** All probe-related work is owned by the future agent layer.

At a high level, when a probe eventually runs on an asset:

- It resolves the asset's canonical ID via MAR.
- It queries bound Historian/CMMS/Document/Log MCP servers using that canonical ID.
- It materializes Asset and Tag nodes in the KG on first reference (lazy materialization).
- It writes findings (`Probe`, `FailureEvent`) back into the KG.

The data layer's job is to make sure MAR, the KG ontology + skeleton, and the MCP server tools are ready and consistent so the agent layer has reliable raw material.

---

## 7. MCP Servers and Tools

The platform exposes data access to future agents through **one MCP server per canonical entity category**. Phase 1 ships these MCP servers as the platform's stable data-access surface — even before any AI agent uses them, the same MCP tools are how internal UI code, the onboarding pipeline, and test simulators talk to the data layer.

### 7.1 MCP servers in Phase 1

| MCP server     | Backed by                              | Reads/writes                        |
| -------------- | -------------------------------------- | ----------------------------------- |
| **Asset MCP**  | MAR + KG hierarchy skeleton            | Read assets, walk hierarchy         |
| **Tag MCP**    | Bound Historian connector              | Discover tags for asset, fetch time-series |
| **Work Order MCP** | Bound CMMS connector               | Search/fetch work orders for asset  |
| **Document MCP** | Bound Document Repository connector  | Search/fetch documents for asset    |
| **Operator Log MCP** | Bound Operator Logs connector    | Search logs for asset / time-range  |
| **KG MCP**     | Knowledge graph                        | Ontology lookups, hierarchy queries, write probe state (later) |

### 7.2 Tool naming discipline

- **Tool names use entity vocabulary, never vendor vocabulary.** `work_order.list_for_asset(canonical_id)`, never `maximo_search_wo(...)`. This is a hard rule.
- **Tool inputs and outputs use canonical IDs for assets.** Vendor IDs may appear inside payloads (e.g., a work order has a `vendor_work_order_id`) but never as a primary identifier on the tool surface.
- **Each MCP server has an adapter layer** that translates between the entity-shaped tool interface and the bound source system. Replacing PI Historian with IP.21 should change adapter config only, not change any tool name or signature.

### 7.3 Phase 1 MCP tool catalog (target)

The detailed tool list (names, params, return shapes) is a separate artifact, but the categories per server are:

**Asset MCP:**
- `asset.get(canonical_id)` → asset record
- `asset.find_by_vendor_id(source_system_id, vendor_id)` → canonical_id
- `asset.find_by_display_name(plant_id, name)` → candidates
- `asset.list_in_unit(unit_id)` → asset list

**Tag MCP:**
- `tag.discover_for_asset(canonical_id)` → list of vendor tags + metadata (queries the bound Historian)
- `tag.get_history(asset_id, vendor_tag, time_range)` → time-series payload
- `tag.get_fft(asset_id, vendor_tag, time_range, params)` → spectrum

**Work Order MCP:**
- `work_order.list_for_asset(canonical_id, lookback)` → work order list
- `work_order.get(vendor_id)` → full record
- `work_order.search(asset_id, keywords, lookback)` → matches

**Document MCP:**
- `document.list_for_asset(canonical_id, types?)`
- `document.fetch(vendor_uri)` → bytes + metadata

**Operator Log MCP:**
- `operator_log.search(asset_id, time_range, keywords?)` → log entries

**KG MCP:**
- `kg.get_node(canonical_id)`
- `kg.walk_hierarchy(from_node, direction, depth)`
- `kg.lookup_ontology(asset_class)` → failure modes / mechanisms / causes
- (Write tools for probe state are deferred to the agent-layer scope.)

---

## 8. Connectors and Simulators

The platform already has connector implementations and simulators for several source systems. Phase 1 hardens them against the spec's data-model discipline.

### 8.1 Connector responsibilities

- Implement the read interface required by its MCP server (e.g., a PI AF connector must support hierarchy crawl + asset record fetch for the Asset MCP).
- Translate vendor-native records into the platform's canonical shape at the MCP boundary.
- Never expose vendor IDs as primary identifiers in MCP responses (except where the spec explicitly allows — e.g., work-order `vendor_id` as an internal payload field).
- Implement test/health-check endpoints that the Connections page can hit.

### 8.2 Simulator responsibilities

- For each supported connector type, ship a simulator that produces realistic vendor records (PI AF hierarchy, PI Historian tags + time-series, Maximo work orders, etc.).
- Simulators must support deterministic seeding so test scenarios are reproducible.
- Simulators must expose the same MCP-facing interface as real connectors so they're swappable.

### 8.3 Phase 1 simulator coverage

- ✅ PI AF simulator (Asset Hierarchy)
- ✅ PI Historian simulator (Tag / time-series)
- ✅ Maximo simulator (CMMS / work orders)
- ✅ SharePoint simulator (Documents)
- ✅ PI Event Frames simulator (Operator Logs)

---

## 9. Out of Scope for Phase 1 (explicitly deferred)

- **TRS** (Tag Resolution Service) — tags are not registered.
- **Multi-source per category** — adding a second historian or CMMS to one plant is a future story.
- **Work-order / document / operator-log canonical registries.**
- **Audit / rollback UIs for binding corrections** — schema supports it (`effective_to`, `superseded`), UI deferred.
- **Probe orchestration, AI agents, model selection, model routing, RCA reasoning logic** — owned by the agent-layer spec, not this one.
- **Asset and Tag node materialization in the KG** — happens at probe time (agent layer).
- **Fleet pattern detection across plants** — warm-KG feature, deferred.
- **On-prem and air-gapped deployments.**

---

## 10. Success Criteria for Phase 1

The data layer is complete when:

1. A user can navigate to the Connections page, pick a category, pick a connector, enter credentials, test, and save the connection.
2. The Connections page enforces "one source per category per plant" with an explicit override flow for replacement.
3. The user can click "Run onboarding pipeline" and the pipeline executes against currently bound Asset Hierarchy connection(s), with partial coverage of other categories supported.
4. Onboarding never auto-fires when a connector is added — only on explicit user action.
5. After onboarding, `mar_assets` and `mar_asset_bindings` are populated; `Site` and `Unit` nodes exist in the KG; no `Asset` nodes are in the KG.
6. Low-confidence bindings appear in the Resolution Queue and can be accepted / replaced with an alternate / rejected.
7. Onboarding can be re-run; runs are idempotent (deltas only).
8. Each MCP server exposes tools named in entity vocabulary, with canonical IDs at the tool boundary.
9. Connectors and simulators implement the MCP-facing interfaces consistently and can be swapped without changing tool names.
10. The KG contains no vendor IDs as node identifiers or primary properties.

---

## 11. Glossary

| Term            | Meaning                                                                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------------------- |
| MAR             | Master Asset Registry. Postgres-backed flat table of canonical assets + their vendor bindings.                       |
| Canonical ID    | Platform-minted identifier for an asset. Format: `asset:{plant}:{unit}:{name}`. Stable across vendor system changes. |
| Vendor ID       | Raw identifier used by a source system (e.g., PI AF path, Maximo asset number).                                      |
| Hierarchy skeleton | The `Site` → `Unit` nodes of the plant in the KG, materialized at onboarding.                                     |
| Ontology layer  | The ISO 14224 reference nodes in the KG, pre-loaded at platform install.                                             |
| Binding         | A row in `mar_asset_bindings` mapping a vendor ID to a canonical ID for one source system.                           |
| Resolution      | The process of assigning a canonical ID to a vendor record (exact-match, rule-based, LLM-suggested, or manual).      |
| Category        | User-facing grouping of connectors (Asset Hierarchy, Historian, CMMS, Document Repository, Operator Logs).           |
| MCP server      | A per-entity-category data-access service exposing entity-shaped tools to internal callers and (later) AI agents.    |
