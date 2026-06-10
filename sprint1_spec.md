# Sprint 1 Spec — Foundation Cleanup & Hierarchy Source

**Sprint goal:** Land the three foundational changes that unblock the Phase 1 control layer (KG + Connections API + Onboarding pipeline).

**Audited against:** `rca_phase1_data_layer_spec.md` + `phase1_gap_analysis.md` (2026-06-10).

**Scope:** Three parallel work items — no AI/agent/probe code, no KG, no Connections API, no Onboarding pipeline (those are Sprint 2+).

**Decisions locked for this sprint:**
- **Identity model:** UUID PKs stay; add `canonical_id TEXT UNIQUE` as the tool-boundary / human-facing identifier. Format: `asset:{plant}:{unit}:{name}` (lowercase, hyphen-separated). Canonical IDs are minted by MAR; vendor IDs never appear in canonical strings.
- **CMMS source for Phase 1:** Maximo only. `sap_pm` connector is parked (kept in repo, excluded from default workspace/test runs).
- **No UI:** All surfaces are FastAPI endpoints with OpenAPI/Swagger documentation. No React/Vue/Streamlit.

---

## Work Item 1 — Remove TRS from Phase 1

**Goal:** TRS is explicitly out of scope per Phase 1 spec §2.3 and §9. Remove the implementation and infra wiring; keep docs but flag as deferred.

### 1.1 Delete

- `packages/trs/` entire package directory (src, migrations, seed_data, tests, pyproject.toml)
- `infra/initdb/01-create-trs-db.sql`

### 1.2 Update

- **`pyproject.toml` (workspace root):** remove `"packages/trs"` from workspace members (line 5)
- **`Taskfile.yaml`:** remove tasks `trs:db:up`, `trs:db:down`, `trs:migrate`, `trs:db`, `test:trs`, `parity:trs-wire` (lines 132–165)
- **`packages/contracts/src/rca_contracts/_ids.py`:** keep `SignalID` type alias as `UUID` for now (placeholder — connectors still typed on it; full removal happens in Sprint 3 MCP restructure). Add a `# DEPRECATED: removed in Sprint 3 — Phase 1 has no signal registry` comment above it.

### 1.3 Mark deferred (do not delete)

Add a frontmatter banner to each of these saying `**Status: Deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**`:
- `docs/trs/` (4 files)
- `docs/superpowers/plans/2026-06-06-trs.md`
- `docs/superpowers/specs/2026-06-06-trs-design.md`
- `docs/adrs/0001-tag-resolution-service.md`

### 1.4 Acceptance

- `grep -r "rca_trs" packages/ infra/ Taskfile.yaml pyproject.toml` returns zero hits outside `docs/`.
- `task test` (full test run) passes with no TRS modules loaded.
- `docker compose -f infra/docker-compose.yaml up` does not create a `trs` database.
- No Python module outside `docs/` imports `rca_trs`.

---

## Work Item 2 — MAR Schema Alignment

**Goal:** Bring `mar_assets` and `mar_asset_bindings` into alignment with Phase 1 spec §2.1–§2.3, using the dual-key identity model (UUID PK + canonical_id TEXT unique).

### 2.1 `assets` table — additive migration

Add columns (all NULLABLE for backfill, then enforce NOT NULL after seed update):

| Column | Type | Notes |
|---|---|---|
| `canonical_id` | TEXT | UNIQUE, NOT NULL. Format `asset:{plant}:{unit}:{name}`. Computed during seed/onboarding from `plant_id` + `parent_unit` + `tag`. |
| `plant_id` | TEXT | NOT NULL. Derived from tenant config; for refplant fixtures use `"refinery-gc"`. (Keep existing `tenant_id` UUID — they coexist; `plant_id` is the human-facing scope used in canonical_id.) |
| `status` | TEXT | NOT NULL, default `'active'`. Enum: `'active'`, `'decommissioned'`, `'pending_review'`. Replaces `decommissioned_at` semantics (keep `decommissioned_at` as a timestamp for the moment of transition, but `status` is authoritative). |
| `attributes` | JSONB | NULLABLE. Class-specific fields (e.g. pump curve params, motor kW) that don't warrant their own column. Existing typed columns (`manufacturer`, `model`, `serial_number`, `description`, `location_description`) stay — they're convenient. |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()`. |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `now()`. Trigger or app-layer update on row change. |

### 2.2 `assets` table — REMOVE

- **Drop `parent_asset_id` FK column.** Hierarchy is moving to KG (Sprint 2). For Sprint 1, just drop it and remove all code paths that read/write it.

### 2.3 `asset_aliases` table — additive migration

Rename in code is optional (we can keep table name `asset_aliases` to avoid a destructive rename), but ADD these columns to bring it in line with spec `mar_asset_bindings`:

| Column | Type | Notes |
|---|---|---|
| `source_system_type` | TEXT | NOT NULL. Enum: `'asset_hierarchy'`, `'historian'`, `'cmms'`, `'document'`, `'operator_log'`. (Categories from spec §4.1.) |
| `vendor_path` | TEXT | NULLABLE. e.g. PI AF path `\\Refinery\Unit21\P-2103A`. Captured from source at crawl time. |
| `vendor_metadata` | JSONB | NULLABLE. Raw source record retained on the binding. |
| `resolution_status` | TEXT | NOT NULL, default `'auto_resolved'`. Enum: `'auto_resolved'`, `'pending_review'`, `'human_validated'`, `'superseded'`, `'rejected'`. |
| `candidate_alternatives` | JSONB | NULLABLE. Top-N alternative canonical_ids with scores when resolution was ambiguous: `[{"canonical_id": "...", "confidence": 0.81, "method": "rule:pump_tag_pattern"}]`. |
| `resolved_by` | TEXT | NULLABLE. `'system'`, `'rule:<id>'`, `'llm_v<n>'`, or a user identifier. |
| `resolved_at` | TIMESTAMPTZ | NOT NULL, default `now()`. |
| `validated_by` | TEXT | NULLABLE. User identifier when status transitions to `human_validated`. |
| `validated_at` | TIMESTAMPTZ | NULLABLE. Timestamp of human validation. |

Keep existing columns: `confidence`, `mapping_source` (these map to spec's `resolution_confidence` and `resolution_method` — document the mapping in the model docstring rather than renaming).

### 2.4 Resolution method vocabulary

Update `resolution.py` to write `resolved_by` values using spec vocabulary:
- `'exact_match'` for `find_active_alias` short-circuit
- `'rule:tag_pattern'` for the regex tag heuristic (instead of generic `'regex_heuristic'`)
- `'manual'` for human-confirmed
- LLM classifier not implemented yet (Sprint 3) — placeholder `'llm_v1'` not yet used

### 2.5 Auto-accept threshold

Update `server.py` default `min_confidence` from `0.85` → `0.92` (Phase 1 spec value). Make it configurable via env var `MAR_AUTO_ACCEPT_THRESHOLD`. Below threshold → write `resolution_status='pending_review'` with `candidate_alternatives` populated, instead of the current `asset_aliases_unresolved` table flow.

### 2.6 `asset_aliases_unresolved` table

Deprecate but do not drop in this sprint. Add a model docstring: `# DEPRECATED: Sprint 3 will replace with resolution_status='pending_review' on asset_aliases. Kept for backwards compat with existing tests until Sprint 3.`

### 2.7 MCP tool changes

- **`assets.get_hierarchy`** — REMOVE. Hierarchy lives in KG starting Sprint 2; until then there is no hierarchy tool. Delete from `server.py:67-114`. Remove its test.
- **`assets.get`** — accept either `asset_id: UUID` OR `canonical_id: str`. If both provided, error. If neither, error. Return shape unchanged (includes both IDs).
- **`assets.resolve`** — return canonical_id in the response payload alongside the UUID.
- **`assets.search`** — add optional `canonical_id_pattern` parameter (glob/LIKE).

### 2.8 Seed updates

- `packages/mar/seed_data/refplant_assets.yaml`: remove `parent_unit` field from each asset (no longer stored in MAR). Add `plant_id: refinery-gc` at the top of the file. Canonical IDs are computed at seed-load time from `plant_id` + asset name (the unit info needed for canonical_id construction needs to come from somewhere — for Sprint 1, add a `unit: cdu` etc. field per asset just for canonical_id construction, with a clear comment that this field is NOT persisted as a column; it's consumed only to mint canonical_id then discarded).
- `seed.py`: compute `canonical_id = f"asset:{plant_id}:{unit_slug}:{name_slug}"` where slugs are lowercased and hyphen-separated.

### 2.9 Acceptance

- All new columns present in `0002_*.py` migration (additive only; no column renames in this sprint).
- `parent_asset_id` removed from model and DB.
- `assets.get_hierarchy` MCP tool removed; no test references it.
- `MAR_AUTO_ACCEPT_THRESHOLD` env var honored; default `0.92`.
- `seed.py` produces canonical IDs of form `asset:refinery-gc:cdu:p-2103a` for the refplant fixture.
- All existing MAR tests updated and passing; one new test asserts canonical_id uniqueness and format regex.
- `task test:mar` passes.

---

## Work Item 3 — PI AF Simulator (Asset Hierarchy)

**Goal:** Add the PI AF API surface to the existing PI simulator so the (Sprint 2) Asset Hierarchy connector has something to crawl. Fixture data already exists; only the API endpoints are missing.

### 3.1 Endpoints to add to `rca_simulator/rca_simulator/pi/app.py`

PI AF Web API shapes (vendor-fidelity required — connectors need to look like real PI AF):

| Method | Path | Returns |
|---|---|---|
| GET | `/assetdatabases` | List asset databases for the PI System. For refplant, return one DB named `Refinery-GC`. |
| GET | `/assetdatabases/{webId}` | Single asset database by WebID. |
| GET | `/assetdatabases/{webId}/elements` | Root elements (Sites) of the database. Supports `?nameFilter=` and `?searchFullHierarchy=true/false`. |
| GET | `/elements/{webId}` | Single element (Site / Unit / Asset) by WebID. Response includes `Path`, `Name`, `Description`, `TemplateName`, `CategoryNames`, `HasChildren`. |
| GET | `/elements/{webId}/elements` | Child elements of an element. Supports `?nameFilter=`, `?searchFullHierarchy=true/false`, `?maxCount=`. |
| GET | `/elements/{webId}/attributes` | Attributes of an element (manufacturer, model, criticality, ISO 14224 class, etc.) — flat list. |

### 3.2 WebID encoding

Reuse the existing `webid` encode/decode utility in `rca_simulator/rca_simulator/pi/webid.py`. Hierarchy WebIDs encode the element's `pi_af_path` (e.g. `\\Refinery-GC\Unit21\P-2103A`) using the same SHA-256-derived deterministic scheme already used for streams. **Critical: same `pi_af_path` always produces same WebID across simulator restarts** (matches PI AF semantics).

### 3.3 Fixture mapping

`rca_simulator/fixtures/refplant/plant.yaml` already defines the Site → Area → Unit → Asset tree. Walk it at startup to build an in-memory element index:

- Root element: Site `Refinery-GC`
- Children: Areas (e.g. `Area-CDU`)
- Grandchildren: Units (e.g. `Unit-21`)
- Leaf children: Assets (e.g. `P-2103A`) with attributes populated from the asset fixture row

Element attributes pulled from fixture:
- `Manufacturer`, `Model`, `SerialNumber`, `Criticality`, `ISO14224Class`, `ISO14224Level`, `ServiceDescription`, `LocationDescription`

### 3.4 Test additions

In `rca_simulator/tests/`:
- `test_pi_af_hierarchy.py`: list databases → walk Site → Area → Unit → Asset → attributes. Assert known refplant pump `P-2103A` is reachable via path `/elements/{site_webid}/elements?nameFilter=Area-CDU` → drill down.
- `test_pi_af_webid_stability.py`: encode the same `pi_af_path` twice across two simulator instances; assert identical WebIDs.
- Update `test_cross_source_coherence.py` to verify the PI AF view of `P-2103A` matches the Maximo `EQUNR` and PI Historian streams for that asset (vendor IDs differ; canonical asset identity matches in fixture seed data).

### 3.5 Acceptance

- `curl http://localhost:<pi-port>/assetdatabases` returns the `Refinery-GC` database.
- `curl .../elements/{site_webid}/elements?searchFullHierarchy=true` returns every asset in the fixture.
- All three new/updated tests pass.
- `task sim:up` followed by `task test:sim` is green.
- No fixture data changes; only the API surface is added.

---

## Cross-cutting acceptance

A successful Sprint 1 means **all of the following are true simultaneously**:

1. `grep -r "rca_trs\|packages/trs\|parity:trs" .` returns zero hits outside `docs/`.
2. `parent_asset_id` does not appear in any model, migration, query, or seed file.
3. `assets.get_hierarchy` MCP tool is gone; no test, no docstring references it.
4. Every asset row has a non-null `canonical_id` matching regex `^asset:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$`.
5. PI AF simulator returns the full refplant hierarchy via `/assetdatabases` → `/elements` traversal.
6. Default test run (`task test`) is green end-to-end with all packages.
7. The full repo can be brought up with `task sim:up && task db:up && task db:migrate && task test` — no manual fixup steps.
8. `infra/docker-compose.yaml` provisions only Postgres (no graph DB yet — that's Sprint 2).
9. OpenAPI schemas for any new HTTP endpoints (PI AF sim) are visible at `/docs` (FastAPI default).
10. No new code touches: KG, Connections table/API, Onboarding pipeline, Asset Hierarchy connector. (Those are Sprint 2.)

---

## Out of scope (explicitly defer to later sprints)

- KG provisioning, ISO 14224 ontology, Site/Unit projection — **Sprint 2**
- `connections` table, Connections API, one-source-per-category enforcement — **Sprint 2**
- Onboarding pipeline, manual trigger endpoint — **Sprint 2**
- Asset Hierarchy connector (PI AF crawler) — **Sprint 2** (after PI AF simulator from this sprint exists)
- MCP per-entity restructure, `tag.*` / `work_order.*` / `document.*` / `operator_log.*` tool renames — **Sprint 3**
- LLM classifier, top-3 candidate scoring with eval data — **Sprint 3**
- KG MCP server (`kg.*` tools) — **Sprint 3**
- Connector health-check endpoints — **Sprint 2** (just before Connections API)
- `SignalID` full removal from contracts/SDK — **Sprint 3** (coupled with MCP restructure)
