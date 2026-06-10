# Sprint 1 State Report — Post-Sprint Codebase Snapshot

**Date:** 2026-06-10 · **Basis:** live codebase inspection after Sprint 1 completion (all payloads below captured from the running code, not transcribed from specs). Read-only audit; no code was modified.

**Sprint outcome recap:** WI1 (TRS removal), WI2 (MAR schema alignment), WI3 (PI AF simulator) all landed; product suite 116 passed / 13 skipped, simulator suite 153 passed, ruff + mypy clean, migration chain 0001→0002 verified against live Postgres during the sprint.

---

## (a) Actual schemas — `assets` and `asset_aliases`

Source of truth: [models.py](packages/mar/src/rca_mar/models.py) + migrations [0001_initial.py](packages/mar/migrations/versions/0001_initial.py) / [0002_phase1_alignment.py](packages/mar/migrations/versions/0002_phase1_alignment.py). ORM and migrations are column-for-column consistent (verified during the sprint's reviews).

### `assets`

| Column | Type | Constraints / default | Notes |
|---|---|---|---|
| `asset_id` | UUID | **PK** | UUIDv7 in seed data |
| `canonical_id` | TEXT | **NOT NULL, UNIQUE** (`uq_assets_canonical_id`) | `asset:{plant}:{unit}:{name}`, lowercase-hyphen slugs |
| `tenant_id` | UUID | NOT NULL, indexed | coexists with `plant_id` |
| `plant_id` | TEXT | NOT NULL | human-facing scope used in canonical_id (`refinery-gc`) |
| `iso14224_class` | VARCHAR | NOT NULL | e.g. `pump.centrifugal` |
| `iso14224_level` | INTEGER | NOT NULL | |
| `tag` | VARCHAR | NOT NULL | display tag, e.g. `P-101A` |
| `service` | VARCHAR | NULL | |
| `criticality` | VARCHAR(1) | NOT NULL | `A`/`B`/`C`/`D` (seed maps high→A, medium→C, low→D) |
| `status` | TEXT | NOT NULL, default `'active'` | enum-by-convention: `active` / `decommissioned` / `pending_review`; authoritative lifecycle field |
| `attributes` | JSONB | NULL | class-specific fields; no write path populates it yet |
| `manufacturer` | VARCHAR | NULL | |
| `model` | VARCHAR | NULL | |
| `serial_number` | VARCHAR | NULL | |
| `commissioned_at` | TIMESTAMPTZ | NULL | |
| `decommissioned_at` | TIMESTAMPTZ | NULL | records transition moment only; `status` is authoritative |
| `location_description` | TEXT | NULL | |
| `description` | TEXT | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL, server default `now()` | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, server default `now()`, app-layer `onupdate` + explicit refresh in the PG upsert's conflict branch | |

Indexes (from 0001): `ix_assets_tenant_class (tenant_id, iso14224_class)`, `ix_assets_tenant_tag (tenant_id, tag)`. The old `parent_asset_id` column and `ix_assets_tenant_parent` index are **dropped** by 0002 — hierarchy has no representation in MAR.

### `asset_aliases`

| Column | Type | Constraints / default | Notes |
|---|---|---|---|
| `alias_id` | UUID | **PK** | |
| `asset_id` | UUID | NOT NULL, FK → `assets.asset_id`, indexed | |
| `tenant_id` | UUID | NOT NULL | |
| `source_system` | VARCHAR | NOT NULL | source key: `maximo` / `sap_pm` / `pi_af` / `uns` |
| `source_system_type` | TEXT | NOT NULL | category per Phase 1 §4.1: `asset_hierarchy` / `historian` / `cmms` / `document` / `operator_log`; mapping owned by `SOURCE_SYSTEM_CATEGORIES` in models.py |
| `external_id` | VARCHAR | NOT NULL | vendor id |
| `vendor_path` | TEXT | NULL | e.g. PI AF path; no write path populates it yet (Sprint 2 crawler) |
| `vendor_metadata` | JSONB | NULL | raw source record; no write path yet |
| `valid_from` | TIMESTAMPTZ | NOT NULL | supersession: closing a row sets the old row's `valid_to` to the new row's `valid_from` (both repos) |
| `valid_to` | TIMESTAMPTZ | NULL (NULL = active) | |
| `mapping_source` | VARCHAR | NOT NULL | = spec's `resolution_method`: `authoritative_import` / `exact_match` / `rule:tag_pattern` / `cross_walk` / `manual` (reserved) / `llm_v<n>` (reserved) |
| `confidence` | FLOAT | NOT NULL | = spec's `resolution_confidence` |
| `resolution_status` | TEXT | NOT NULL, default `'auto_resolved'` | `auto_resolved` / `pending_review` / `human_validated` / `superseded` / `rejected` (last two have no write path yet) |
| `candidate_alternatives` | JSONB | NULL | `[{"canonical_id", "confidence", "method"}]`, written on pending-review demotion |
| `resolved_by` | TEXT | NULL | `'system'` on all automated writes |
| `resolved_at` | TIMESTAMPTZ | NOT NULL, server default `now()` | |
| `validated_by` | TEXT | NULL | no write path yet (Sprint 3 review tooling) |
| `validated_at` | TIMESTAMPTZ | NULL | no write path yet |
| `is_primary` | BOOLEAN | NOT NULL, default false | |
| `confirmed_by` | VARCHAR | NULL | pre-existing column, carried over on demotion |
| `notes` | TEXT | NULL | |

Unique partial index (from 0001): `(tenant_id, source_system, external_id) WHERE valid_to IS NULL` — at most one active binding per vendor id per source.

**Behavioral invariants encoded in resolution** ([resolution.py](packages/mar/src/rca_mar/resolution.py)): rows with `resolution_status='human_validated'` or `mapping_source='manual'` are never auto-demoted (human overrides the threshold); below-threshold demotion happens exactly once (idempotent — no row churn on repeated resolves) and carries over provenance fields; unknown source systems never get a guessed `source_system_type` (they fall back to the unresolved queue).

### `asset_aliases_unresolved` (deprecated, retained)

`(tenant_id, source_system, external_id)` composite PK, `first_seen_at`, `occurrence_count`, `last_attempt_at`, `candidate_payload` JSONB. Still receives: no-candidate misses, ambiguous multi-candidate crosswalks, and unknown-source-system cases. Marked `# DEPRECATED` pending Sprint 3.

---

## (b) MAR MCP server — tools, signatures, live payloads

Server: [server.py](packages/mar/src/rca_mar/server.py), built via `make_mar_mcp(repo, tenant_id, regex_patterns?)`. Exactly three tools are exposed: **`assets.resolve`, `assets.get`, `assets.search`** (`assets.get_hierarchy` removed this sprint; pinned by `test_exposed_tools_are_exactly_resolve_get_search`). Every response is `ToolResponse[T]` — exactly one of (`data`+`provenance`) or `error`.

**Wire-shape note:** `AssetDescriptor` (the payload type) carries `asset_id`, `canonical_id`, `tenant_id`, `plant_id`, class/level/tag/service/criticality, nameplate, timestamps of commissioning — but **not** `status`, `attributes`, `created_at`, `updated_at` (DB-side only this sprint).

### `assets.resolve(request: ResolveRequest)` → `ToolResponse[ResolveAssetOutput]`

```python
class ResolveRequest(BaseModel):
    external_id: str
    source_system: str
    time: AwareDatetime | None = None          # temporal alias lookup (valid_at)
    min_confidence: float | None = None        # None -> MAR_AUTO_ACCEPT_THRESHOLD (env, default 0.92)
```

Live payload — exact match (`CRDU-P101A` @ `maximo`):

```json
{
  "data": {
    "status": "resolved",
    "asset": {
      "asset_id": "0190d3c9-0000-7000-8000-000000000001",
      "canonical_id": "asset:refinery-gc:unit-101:p-101a",
      "tenant_id": "0190d3c9-0000-7000-8000-0000000000ff",
      "plant_id": "refinery-gc",
      "iso14224_class": "pump.centrifugal",
      "iso14224_level": 6,
      "tag": "P-101A",
      "service": "charge pump",
      "criticality": "A",
      "manufacturer": "Sulzer",
      "model": "AHLSTAR-A22-50",
      "serial_number": "SN-2018-00471",
      "commissioned_at": null, "decommissioned_at": null,
      "location_description": null, "description": null
    },
    "canonical_id": "asset:refinery-gc:unit-101:p-101a",
    "confidence": 1.0,
    "mapping_source": "exact_match",
    "alternatives": []
  },
  "provenance": {
    "tool_name": "assets.resolve", "tool_version": "0.1.0", "source": "mar",
    "source_query": "resolve maximo:CRDU-P101A",
    "queried_at": "2026-06-10T23:15:04Z", "response_id": "83037099-…",
    "record_count": 1, "truncated": false,
    "raw_tags": ["maximo:CRDU-P101A"], "notes": null
  },
  "error": null
}
```

Unknown id (`status: "unresolved"` is a **successful** result, not an error):

```json
{ "data": { "status": "unresolved", "asset": null, "canonical_id": null,
            "confidence": 0.0, "mapping_source": "none", "alternatives": [] },
  "provenance": { "...": "record_count: 0" }, "error": null }
```

Other statuses: `"ambiguous"` (multiple equal crosswalk candidates; `alternatives` lists the candidate `AssetDescriptor`s).

### `assets.get(request: GetRequest)` → `ToolResponse[AssetDescriptor]`

```python
class GetRequest(BaseModel):
    asset_id: UUID | None = None
    canonical_id: str | None = None     # exactly one of the two must be set (XOR)
```

Live payload — by canonical id (`asset:refinery-gc:unit-201:p-103a`): returns the full `AssetDescriptor` (P-103A, `criticality: "D"`, `model: "OH2-200"`) with `record_count: 1`. Missing id → `error.code = "not_found"`. XOR violation (both or neither key):

```json
{ "data": null, "provenance": null,
  "error": { "code": "validation_failed",
             "message": "assets.get requires exactly one of asset_id or canonical_id",
             "retryable": false, "details": null } }
```

### `assets.search(request: SearchRequest)` → `ToolResponse[list[AssetDescriptor]]`

```python
class SearchRequest(BaseModel):
    iso14224_class: str | None = None
    tag_pattern: str | None = None              # NOTE: substring semantics in-memory (pre-existing divergence vs PG LIKE, deferred)
    canonical_id_pattern: str | None = None     # SQL LIKE semantics (%/_), parity-tested across both repos
    criticality: list[str] | None = None
    service: str | None = None
    limit: int = 50
```

Live payload — `canonical_id_pattern: "asset:refinery-gc:unit-101:%"` returns exactly the P-101A descriptor, with provenance `source_query: "search class=None tag=None canonical_id=asset:refinery-gc:unit-101:%"` and `raw_tags: ["P-101A"]`.

---

## (c) PI AF simulator — six endpoints with live responses

Served by the PI simulator app ([pi/app.py](rca_simulator/rca_simulator/pi/app.py) + [pi/af_hierarchy.py](rca_simulator/rca_simulator/pi/af_hierarchy.py)), port 8001 under compose, alongside the four pre-existing historian/event-frame routes. OpenAPI at `/docs`. WebIDs deterministically encode the synthesized AF path (`\\PI-DEMO\Refinery-GC\…`) — same path ⇒ same WebID across restarts; element WebIDs are provably disjoint from stream WebIDs. AF database name is env-overridable (`PI_AF_DATABASE`, default `Refinery-GC`).

**1. `GET /assetdatabases`**

```json
{ "Items": [ { "WebId": "S1XFxQSS1ERU1PXFJlZmluZXJ5LUdD", "Name": "Refinery-GC",
               "Description": "AF database for Demo Refinery",
               "Path": "\\\\PI-DEMO\\Refinery-GC" } ] }
```

**2. `GET /assetdatabases/{webId}`** — the same object un-enveloped; unknown WebID → 404.

**3. `GET /assetdatabases/{webId}/elements`** — root elements (the Site). Supports `nameFilter` (case-insensitive `*`/`?` glob), `searchFullHierarchy` (true ⇒ includes the root site + all descendants = 10 elements), `maxCount`.

```json
{ "Items": [ { "WebId": "S1XFxQSS1ERU1PXFJlZmluZXJ5LUdDXFNJVEUtREVNTw",
               "Name": "SITE-DEMO", "Description": "Demo Refinery",
               "Path": "\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO",
               "TemplateName": "Site", "CategoryNames": ["Site"], "HasChildren": true } ] }
```

**4. `GET /elements/{webId}`** — single element:

```json
{ "WebId": "S1XFxQSS1ERU1PXFJlZmluZXJ5LUdDXFNJVEUtREVNT1xBUkVBLTEwMFxVTklULTEwMVxQLTEwMUE",
  "Name": "P-101A", "Description": "charge pump",
  "Path": "\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO\\AREA-100\\UNIT-101\\P-101A",
  "TemplateName": "centrifugal_pump", "CategoryNames": ["Asset"], "HasChildren": false }
```

**5. `GET /elements/{webId}/elements`** — children, same query params. Children of UNIT-101 → P-101A + P-101B items. From the Site with `searchFullHierarchy=true` → **strict descendants** (9 elements; PI semantics — the DB-level query includes the root, the element-level query does not):

```json
["AREA-100", "UNIT-101", "P-101A", "P-101B", "UNIT-102", "P-102A", "AREA-200", "UNIT-201", "P-103A"]
```

**6. `GET /elements/{webId}/attributes`** — flat `{WebId, Name, Value}` list (assets only; containers return empty `Items`):

```json
{ "Items": [
  { "WebId": "…fE1hbnVmYWN0dXJlcg", "Name": "Manufacturer",       "Value": "Sulzer" },
  { "WebId": "…",                   "Name": "Model",              "Value": "AHLSTAR-A22-50" },
  { "WebId": "…",                   "Name": "SerialNumber",       "Value": "SN-2018-00471" },
  { "WebId": "…",                   "Name": "Criticality",        "Value": "high" },
  { "WebId": "…",                   "Name": "ISO14224Class",      "Value": "pump.centrifugal" },
  { "WebId": "…",                   "Name": "ServiceDescription", "Value": "charge pump" } ] }
```

Attribute WebIDs use PI's `path|AttrName` convention but are decorative — no route resolves them (commented in code).

---

## (d) Deviations from sprint1_spec.md (with reasons)

| # | Deviation | Reason |
|---|---|---|
| 1 | WI3 tests use real fixture names (`SITE-DEMO`, `AREA-100`, `P-101A`) instead of the spec's `Refinery-GC` site / `Area-CDU` / `P-2103A` examples | The spec's names were illustrative and don't exist in fixtures; acceptance §3.5 ("no fixture data changes", "every asset in the fixture") wins. Only the AF **database** is literally named `Refinery-GC` per §3.1. |
| 2 | WebID scheme is reversible base64, not "SHA-256-derived" as §3.2 describes | §3.2 mischaracterized the *pre-existing* `webid.py` utility; the spec's operative instruction ("reuse the existing utility", determinism) was followed. |
| 3 | Negative `maxCount` returns empty instead of PI's HTTP 400; AF 404 bodies are FastAPI `{"detail"}` not PI `{"Errors":[...]}` | Accepted Sprint-1 fidelity deviations, documented in code comments and [pi/README.md](rca_simulator/rca_simulator/pi/README.md). |
| 4 | Element attributes expose 6 of the 8 names listed in §3.3 (no `ISO14224Level`, `LocationDescription`) | The simulator fixture schema has no such fields; §3.3 said "whichever the fixture schema actually has". |
| 5 | Seed register's `units:` section removed entirely (spec §2.8 only said remove `parent_unit` per asset) | With `parent_asset_id` dropped, unit rows had no purpose and no honest canonical_id; units become KG nodes in Sprint 2. MAR registers leaf assets only. |
| 6 | `mapping_source` kept `'cross_walk'` and seed kept `'authoritative_import'` (§2.4 lists only exact_match / rule:tag_pattern / manual / llm) | §2.4 didn't enumerate the crosswalk or seed paths; renaming them was out of scope. Mapping documented in the `AssetAlias` docstring. |
| 7 | Pending-review semantics refined beyond §2.5's one-liner: human_validated/manual rows are never demoted; demotion is once-only (no row churn); ambiguous multi-candidate and unknown-source cases go to the deprecated unresolved queue, not pending_review | The literal reading (always write pending_review below threshold) churned one row per resolve call and could demote human-curated bindings — caught in spec review, fixed with tests pinning each rule. |
| 8 | `AssetDescriptor` wire shape does not expose new columns `status`/`attributes`/`created_at`/`updated_at` | §2.7 said "return shape unchanged (includes both IDs)" — only `canonical_id`/`plant_id` were added to the wire. |
| 9 | Cross-cutting #2 ("`parent_asset_id` does not appear in any model, migration, query, or seed") — the string appears in migration 0001 (historical create), 0002 (the drop + downgrade), and one contracts test asserting the field is rejected | A drop migration must name the column; a removal-guard test legitimately names what it asserts gone. Live models/queries/seeds are clean. |
| 10 | `sap_pm` parking implemented as a `--ignore` in the Taskfile `test` task; package remains a uv workspace member | Removing it from the workspace would break the explicit `parity:sap`/`parity:cross` tasks and cross-source test imports. Standalone it still passes (2 passed, 1 skipped). |
| 11 | Seed register P-103A entry rewritten (asset_id …0004, unit-201, TKFM-P103A, SAP 10001255, OH2-200) — beyond the sprint text | Final review found the entry contradicted the simulator fixtures on nearly every field (its old UUID actually belonged to fixture P-102A); left as-was it would have wrecked Sprint 2's AF→MAR mapping. |
| 12 | Cross-cutting #7 bring-up was verified with WI2's live-Postgres run (`task mar:db`: migrate + 3 pg tests passed), not re-run at sprint close | Docker Desktop on this machine failed to start during final acceptance; the migration proof from earlier in the sprint stands. |
| 13 | Criticality `D` exists on the wire (seed maps low→D) though Phase 1 spec §2.1 says A/B/C | Pre-existing SPEC-011 design decision; not in Sprint 1 scope to change (explicitly excluded from WI2). Flagged for Sprint 2 vocabulary reconciliation. |

---

## (e) TODO / DEPRECATED / FIXME comments in code

Repo-wide grep over `packages/` and `rca_simulator/` (excluding venvs): **zero `# TODO`, zero `# FIXME`.** Two intentional `# DEPRECATED` markers:

| Location | Comment |
|---|---|
| [_ids.py:9](packages/contracts/src/rca_contracts/_ids.py:9) | `# DEPRECATED: removed in Sprint 3 — Phase 1 has no signal registry` (above `SignalID`) |
| [models.py:120](packages/mar/src/rca_mar/models.py:120) | `# DEPRECATED: Sprint 3 will replace with resolution_status='pending_review' on asset_aliases. Kept for backwards compat with existing tests until Sprint 3.` (on `AssetAliasUnresolved`) |

One adjacent deferral comment (not TODO-tagged): [repository.py:143](packages/mar/src/rca_mar/repository.py:143) — `tag_pattern: known pre-existing LIKE-vs-substring divergence from PG; deferred.`

---

## (f) `task test` output summary

Command: `uv run pytest -q --ignore=packages/connectors/sap_pm` (the sap_pm ignore is the Phase-1 parking). Overall: **116 passed, 13 skipped, 0 failed** (~1.7 s).

| Package | Passed | Skipped | Skip reason |
|---|---|---|---|
| contracts | 27 | 0 | |
| connector_sdk | 23 | 0 | |
| connectors/echo | 1 | 0 | |
| connectors/pi | 3 | 2 | PI simulator not reachable at `127.0.0.1:8001` (run `task parity:pi`) |
| connectors/maximo | 1 | 1 | Maximo simulator not reachable at `127.0.0.1:8002` (run `task parity:maximo`) |
| connectors/documents | 1 | 1 | Docs simulator not reachable at `127.0.0.1:8004` (run `task parity:documents`) |
| connectors/opc_ua | 1 | 2 | OPC UA simulator not reachable at `opc.tcp://127.0.0.1:4840` (run `task parity:opcua`) |
| connectors/mqtt | 10 | 1 | MQTT broker not reachable at `127.0.0.1:1883` (run `task parity:mqtt`) |
| mar | 49 | 5 | 4× Postgres not reachable (run `task mar:db`); 1× Maximo sim not reachable (run `task parity:mar-wire`) |
| cross_source_tests | 0 | 1 | both CMMS sims must be up (8002 + 8003; run `task parity:cross`) |

All 13 skips are by-design environmental gates (live simulator / live DB integration tests that run via their explicit `parity:*` / `mar:db` tasks). Excluded-but-healthy: `sap_pm` standalone = 2 passed, 1 skipped (its parity test). Separate project: `rca_simulator` suite = **153 passed**.

---

## (g) Services started by `docker compose up`

**Product infra** ([infra/docker-compose.yaml](infra/docker-compose.yaml)) — exactly **one** service:

| Service | Image | Ports | Notes |
|---|---|---|---|
| `postgres` | `postgres:16` | 5432 | DB `rca_mar`, user/pass `rca`/`rca`; mounts `./initdb` (now **empty** — the TRS init SQL was removed); pg_isready healthcheck |

No graph DB, no Temporal, no MinIO on the product side — per cross-cutting #8 (KG store arrives in Sprint 2).

**Simulator dev stack** ([rca_simulator/docker-compose.yaml](rca_simulator/docker-compose.yaml), separate project, `task up` from `rca_simulator/`) — 8 services: `mosquitto` (1883), `sim-mqtt`, `sim-opcua` (4840), `sim-pi` (8001 — now also serving the six AF routes), `sim-maximo` (8002), `sim-sap-pm` (8003), `sim-documents` (8004), `minio` (9000/9001).

---

## Considerations for the Sprint 2 spec

Things we learned this sprint that the Sprint 2 spec (KG + Connections API + onboarding pipeline + AF crawler connector) should settle explicitly:

1. **Decide the AF vendor_id, and reconcile the register's `pi_af` aliases.** This is the sharpest landmine. The seed register's `pi_af` external ids are the *legacy* paths (`\\PI-DEMO\Refinery\P-101A`) while the AF simulator's element paths are `\\PI-DEMO\Refinery-GC\SITE-DEMO\AREA-100\UNIT-101\P-101A`. A crawler doing exact-match on element Path will MISS every seeded asset and queue them all as duplicates. Options: (a) treat the element **Name** as the match key, (b) re-key the register's `pi_af` aliases to the AF element paths, or (c) use WebId as `vendor_id` and Path as `vendor_path`. Recommend (c) + a one-time register update; either way the spec must say.
2. **Expect a pending-review flood on first crawl, by design.** Only P-101A and P-103A are in the register; the crawl will discover P-101B and P-102A with no binding. The current resolution pass has no pattern rules that assign class/canonical ids (regex heuristic confidence 0.70 < 0.92 threshold), so crawl-discovered assets land in the review queue. Sprint 2 should either ship the deterministic pattern-rule registry (`rule:<id>` infra is ready in the vocabulary) or explicitly accept the queue-everything behavior for new assets.
3. **Resolution Queue needs new repo write paths.** `resolution_status` transitions (accept → `human_validated`, reject → `rejected`, supersede → `superseded`), `validated_by/validated_at` writes, and `AliasRow` currently omits `resolved_at`/`validated_*` by documented invariant — extending it is a deliberate unlock, do it consciously. Also note `decommissioned`/`superseded`/`rejected` currently have **no write path at all**; pipeline step 5 (decommission-on-removal) creates the first one.
4. **Unit identity must be coherent across three vocabularies**: canonical-id unit slugs (`unit-101`), sim unit ids (`UNIT-101`), and the future KG `Unit` node ids. The slug mapping currently lives only in the seed register's transient `unit:` field. When the KG materializes Units from the AF crawl, define the slugging function once (reuse `seed._slug`) and make KG node ids match the canonical-id segments — Phase 1 spec §3.5 (no vendor ids in KG identifiers) applies.
5. **`SOURCE_SYSTEM_CATEGORIES` needs to become connection-driven.** The 4-entry hardcoded map (`maximo`/`sap_pm`/`pi_af`/`uns`) is the placeholder for what the `connections` table's `category` column should own. Note `operator_log` has no source key at all yet (PI event frames are served but unmapped). Unknown sources currently fail loudly (seed) or fall to the unresolved queue (resolve) — keep that property when connections arrive.
6. **`connections` schema vs current naming**: the Phase 1 spec's `connection_id` format (`refinery-gc.pi-af.prod`) vs the aliases' `source_system` values (`pi_af`) need a declared relationship (the gap analysis flagged this — aliases conflate source identity with connection identity). Decide whether `source_system` becomes the FK to `connections.connection_id` or stays a system-type key.
7. **Wire-shape gap to plan for**: `AssetDescriptor` doesn't expose `status`/`attributes`/`created_at`/`updated_at`. The onboarding summary ("assets registered, bindings pending review") and Resolution Queue UI will need them — either extend the descriptor (breaking-ish) or add dedicated output models for the pipeline/queue endpoints.
8. **Criticality vocabulary**: pick A/B/C (Phase 1 spec) or A–D (current SPEC-011 mapping, `D` already on the wire for P-103A) and reconcile seed mapping + column comment in one move.
9. **Connector health checks come before the Connections API** (pipeline step 1 re-tests connections). None exist on any connector today; the AF crawler connector should be the first to ship one, and the pattern should be SDK-level, not per-connector ad-hoc.
10. **Write the negative trigger test early**: Phase 1 spec §10.4 (onboarding never auto-fires on connector add) is cheap to pin with a test the day the connections API exists, and it's the kind of invariant that silently regresses.
11. **Graph store choice is still open** — docker-compose is deliberately Postgres-only. The old internal docs assumed Neo4j 5.x (`WEEK-1-QUICKSTART` planned `neo4j/init.cypher`); nothing in the codebase constrains the choice yet. Whatever is picked, the ISO 14224 BB1 ontology content (~120 nodes) is authoring work, not just plumbing — budget it separately.
12. **Small debts safe to fold into Sprint 2/3**: `tag_pattern` LIKE-vs-substring divergence (in-memory repo, commented); AF attribute WebIDs are dead-end identifiers (no resolving route); `MAR_AUTO_ACCEPT_THRESHOLD` is env-read per request — a connections-level setting may be the better home; Docker Desktop on this dev machine is slow/flaky to start (CI or a compose pre-flight check would de-risk acceptance runs).

---

*Method: schemas read from ORM + migrations (verified consistent); MCP payloads and PI AF responses captured live from the running code (in-memory repo seeded from the register; TestClient against the simulator app); test counts from fresh runs; grep evidence for comments and compose contents. No code modified.*
