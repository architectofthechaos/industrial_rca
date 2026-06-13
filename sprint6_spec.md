# Sprint 6 Spec — Evidence Quality, Test Safety & Semantic Document Search

> **Status:** DRAFT for execution by Claude Code.
> **Branch:** `feat/sprint-6` off `main` (after Sprint 5 / `feat/sprint-5` merges).
> **Predecessor:** Sprint 5 ran a full live P-101A probe over HTTP transport + dynamic routing
> (8 live defects fixed, 547 tests green). But the live probe currently produces a **thinner RCA
> than the system is capable of**: CMMS work-order evidence is silently skipped, the LLM falls
> back to a generic failure mechanism, and document scoring is keyword-only. Sprint 6 closes the
> **evidence-quality** gaps, fixes a **test-safety** bug, and lands **semantic document search**
> (pgvector) — the real warming-KG value.

---

## 0. Goal

Make the live RCA as good as the architecture allows, safely:
1. **Restore CMMS evidence** — the probe actually uses work-order history (today it's skipped).
2. **Specific failure mechanisms** — the LLM picks a real ISO mechanism, not the `other` fallback.
3. **Fix the test-safety bug** — the suite must never wipe the live `rca_mar` store.
4. **Semantic document search (pgvector)** — embed connected-source documents; gather retrieves
   by cosine similarity (`embedding_v1`) instead of keyword overlap.
5. (Closes the remaining Sprint-4/5 deferrals: real `vector` column + `PostgresResponseCache`.)

**Priority order matters:** WI1–WI3 (quality + safety) come **before** WI4–WI5 (pgvector +
cache). A thin-but-safe probe beats a semantic-search probe that can clobber the live store.

---

## 1. Architectural principles (unchanged)

> Connect-only documents (owner decision, Sprint 5): documents come **only from connected
> sources** (SharePoint-sim today, real SharePoint later) — **no user-upload path**. Sprint 6
> vectorizes whatever lives in the connected `document`-category source, triggered by the
> connection lifecycle, not by file uploads.
> Sources simulated now, real later; the seam stays config-driven.

---

## 2. What ALREADY EXISTS — DO NOT REBUILD

Verified against `feat/sprint-5` at spec-writing time.

| Component | Location | Status |
|---|---|---|
| `VoyageEmbeddingTransport.embed(model, texts) -> list[list[float]]` | `llm/.../transports.py:58` | ✅ live embed path exists |
| `HashEmbeddingTransport` (deterministic, key-free) | `llm/.../testing.py:60` | ✅ test/dev embedding |
| `document_embeddings` table (embedding col = **JSONB**) | `mar/migrations/versions/0005_probe_tables.py:127` | ✅ table exists — migrate col to `vector` |
| `_score_documents(...) -> (..., "embedding_v1"\|"keyword_overlap")` — keyword today | `agents/.../gather_graph.py:215` | ✅ slot for semantic scoring exists, returns `keyword_overlap` |
| document MCP: `search_for_asset`, `get`, `list_by_type`; doc_types `datasheet`/`p_and_id`/`rca_report` | `connectors/documents/.../server.py:47` | ✅ corpus enumeration exists |
| `CanonicalSlugAssetGateway` (default) — `source_handle` **raises NotFound** | `connectors/maximo/.../server.py:125` | ⚠️ this is why WO evidence is skipped (WI1) |
| `AssetGateway` Protocol + `MarAssetGateway` seam (DI point for a real gateway) | `connector_sdk/.../` | ✅ inject a MAR-backed impl, don't rebuild the seam |
| MAR `asset.get`/`asset.resolve` (carries `maximo_location` / source handles) | `mar/.../server.py` | ✅ the source of truth the gateway reads |
| `rca_rank_hypotheses` prompt + `_one_of` enum guards + `failure-mechanism:other` fallback | `agents/.../rca_graph.py:185,306` | ✅ prompt exists — feed it the vocab (WI2) |
| KG ISO 14224 ontology — **102 nodes (FailureMechanisms + FailureModes + classes) seeded in Neo4j** | `kg/seed/iso14224_bb1.cypher` | ✅ query it — do NOT author or inline the full list |
| KG MCP **`kg.list_failure_modes_for_class`** (CAN_EXHIBIT, class-scoped) + `get_ontology_node`/`find_path`/`get_asset_context` | `kg/.../server.py:144` | ✅ GraphRAG query path for WI2 already exists |
| MAR **`asset_aliases`** table (`source_system`+`external_id`→`asset_id`, indexed) | `mar/migrations/versions/0001_initial.py:42` | ✅ the Maximo-location source of truth for WI1 — no new table |
| pgvector-enabled Postgres image (`pgvector/pgvector:pg16`) | `infra/docker-compose.yaml` | ✅ engine ready since Sprint 4 — extension not yet provisioned |
| `InMemoryResponseCache` + `ResponseCache` Protocol | `llm/.../cache.py` | ✅ Protocol exists — add Postgres impl (WI5) |
| `RegistryConnectionRouter`, HTTP transport, `/health` | Sprint 5 | ✅ done — out of scope |

**Out of scope:** user file-upload/ingestion (owner decision: connect-only); P&ID semantic
embedding (structured topology, low text value — keyword/metadata only this sprint); partner
engine; new connectors; UI.

---

## 3. Locked decisions

- **D12 — Priority/sequencing.** WI1 (CMMS evidence) → WI2 (mechanism vocab) → WI3 (test-safety)
  → WI4 (pgvector semantic search) → WI5 (Postgres response cache). Safety + quality before
  semantic search.
- **D13 — MAR-backed asset gateway.** Replace the slug-only gateway in the live composition with
  a `MarAssetGateway` that resolves an asset's source handle (e.g. `maximo_location`) via MAR
  `asset.get`, so `work_order.list_for_asset` returns real WOs. Keep `CanonicalSlugAssetGateway`
  for hermetic tests. A missing/unresolvable handle must be an explicit typed skip with a
  coverage note — **not a silent empty** (consistent with the G19-era no-silent-skip rule).
- **D14 — Failure-mechanism vocabulary (GraphRAG, not inlined).** Do **not** dump the full
  102-node ontology into the prompt. Per-probe, **query the KG via the existing
  `kg.list_failure_modes_for_class` MCP tool** (`server.py:144`) for the asset's equipment class
  (`CAN_EXHIBIT`), and inject only that **scoped, class-relevant** mechanism subset into the
  `rca_rank_hypotheses` prompt. The `other` fallback stays a last resort, not the default. Keep
  `_one_of` guards validating against the queried set.
- **D15 — Embedding model + dims.** Embedding model is **env-configurable** (e.g.
  `EMBEDDING_MODEL`, default `voyage-3` → 1024 dims). `HashEmbeddingTransport` must emit the
  **same dimension** so hermetic tests exercise the real query path. The `vector(N)` column width
  is fixed at migration time to the default model's dim; record it in the migration.
- **D16 — Embedding trigger (connect-only) + stored columns.** Documents are embedded on
  **`document`-connection activation** (and re-embed on refresh); embeddings are tagged with
  `connection_id` and the document's `version`/hash so a disconnect can invalidate them. The
  `document_embeddings` row also stores **`doc_type`** (datasheet/rca_report) and a **`description`**
  column — a **short LLM-generated summary** of the document (one cheap completion at embed time).
  Embed `datasheet` + `rca_report` doc_types first; `p_and_id` excluded this sprint.
- **D17 — pgvector index.** Provision the `vector` extension + an ANN index (IVFFlat or HNSW,
  cosine) on `document_embeddings.embedding`. Migration must be idempotent and not break Temporal
  auto-setup DBs (re-verify, per Sprint 4 D3).

---

## 4. Work Items

### WI1 — Restore CMMS work-order evidence (D13)
**Build:** a `MarAssetGateway` (implementing the `AssetGateway` Protocol) that resolves the
asset's CMMS handle from the **existing `asset_aliases` table** (lookup by
`(source_system="maximo", asset_id)` → `external_id`, the Maximo location), via MAR. Wire it into
the **live** Maximo connector composition (replace `CanonicalSlugAssetGateway` there only).
Unresolvable alias → typed skip + coverage note, never silent-empty. **No new table** — the
alias table + `ix_alias_lookup` index already exist (`0001_initial.py:42`).

**Acceptance:**
- Live P-101A probe's Evidence Package includes **real work-order history** (CMMS coverage `ok`,
  `record_count > 0`), not `skipped`.
- Hermetic tests still use the slug gateway; no regression.
- A genuinely unmapped asset yields an explicit `skipped:*` coverage note (test).

### WI2 — Specific failure mechanisms (D14)
**Build (GraphRAG wiring):** per-probe, call the **existing** `kg.list_failure_modes_for_class`
MCP tool to fetch the **class-scoped** mechanism subset from Neo4j, inject that into the
`rca_rank_hypotheses` prompt, and validate the LLM's choice against it (keep `_one_of`). `other`
only when nothing fits. **No research/authoring, and no inlining the full list** — the ISO 14224
B.4 mechanisms are already seeded in Neo4j (102 ontology nodes; `iso14224_bb1.cypher`) and
queryable via the KG MCP. We query the graph for what's relevant, not prompt-stuff the whole set.

**Acceptance:**
- On the live P-101A seal-leak probe, the primary hypothesis carries a **specific**
  `iso14224_mechanism` (not `failure-mechanism:other`).
- An out-of-vocabulary LLM answer is coerced/guarded (test), still never crashes persist (G26
  invariant holds).

### WI3 — Test-safety: stop the suite clobbering the live store (Sprint 5 carry-over)
**Do:** find the non-hermetic/DB test that wiped live `rca_mar` assets mid-session and isolate it
— dedicated throwaway schema/DB or transactional rollback fixture; never target the live store.
Add a guard so a destructive op cannot run against a non-test database.

**Acceptance:**
- Full suite (incl. DB-gated) runs without mutating/destroying the live `rca_mar` assets
  (verified: asset count + key rows unchanged before/after a full run).
- A guard/fixture makes "destructive op against a non-`test_*` DB" fail fast.

### WI4 — Semantic document search via pgvector (D15, D16, D17)
**Build:**
- Migration: provision `vector` extension; alter `document_embeddings.embedding` JSONB → `vector(N)`
  (N from D15); add **`doc_type`** + **`description`** columns (D16); add the cosine ANN index
  (D17); idempotent; Temporal-safe.
- Embedding pipeline: on `document`-connection activation, enumerate docs (`list_by_type` for
  `datasheet`+`rca_report`), embed each via the configured transport, upsert into
  `document_embeddings` tagged with `connection_id` + doc version/hash (D16).
- Retrieval: change `_score_documents` to embed the query (candidate failure modes / context) and
  rank by cosine similarity against the connected source's embeddings; return `embedding_v1`.
  Fall back to `keyword_overlap` only if embeddings are unavailable.

**Acceptance:**
- A connected source's `datasheet`+`rca_report` docs are embedded and stored as `vector` rows.
- Live gather returns docs scored by **semantic similarity** (`score_method == "embedding_v1"`);
  a relevant prior RCA ranks above a keyword-only match that earlier keyword scoring would miss.
- Hermetic path uses `HashEmbeddingTransport` (same dims) and is deterministic.
- Disconnecting/refreshing a source invalidates/replaces its embeddings.

### WI5 — Postgres response cache (closes Sprint 4/5 deferral)
**Build:** `PostgresResponseCache` implementing the `ResponseCache` Protocol, so determinism
replay works **across processes** (today only `InMemoryResponseCache`). Wire into the live deps.

**Acceptance:**
- A seeded probe's LLM responses persist to Postgres; a replay in a **fresh process** produces
  the byte-identical conclusion (extends the Sprint-4 determinism harness across process
  boundaries).
- Hermetic suite still uses the in-memory cache; no regression.

---

## 5. Cross-cutting acceptance (the "Sprint 6 done" bar)

All hold on the live stack:
1. Live P-101A probe includes **real CMMS work-order evidence** (D13).
2. Primary hypothesis carries a **specific** ISO failure mechanism, not `other` (D14).
3. Full test suite runs without touching the live `rca_mar` store; destructive-op guard in place (WI3).
4. Documents from the connected source are embedded as pgvector `vector` rows; gather scores
   semantically (`embedding_v1`); semantic win demonstrated over keyword (WI4).
5. Cross-process determinism replay via `PostgresResponseCache` (WI5).
6. `ruff` + `mypy` clean (with and without `rca-llm[live]`); hermetic suite (547+) green, no
   regressions; new tests added; pgvector migration doesn't break Temporal auto-setup.
7. A full live P-101A probe completes end-to-end with **richer evidence + a specific conclusion**
   than Sprint 5 produced (the headline: quality, proven).

---

## 6. Gaps-to-verify (code-true; confirm during execution)

- **GAP-1 (WI1):** Maximo uses `CanonicalSlugAssetGateway` whose `source_handle` **raises
  NotFound** (`server.py:125`) → `work_order.list_for_asset` skips; the probe completes with **no
  CMMS evidence**. Confirm a `MarAssetGateway`/`AssetGateway` DI seam exists to swap in.
- **GAP-2 (WI2):** `rca_graph.py:306` hardcodes `iso14224_mechanism="failure-mechanism:other"`
  as fallback; the valid vocab is **not** fed to the rank prompt. Confirm the KG vocabulary +
  class scoping (`CAN_EXHIBIT`).
- **GAP-3 (WI3):** locate the destructive test (Sprint 5 report: it wiped live `rca_mar` assets,
  re-seed restored them). Likely a DB-gated/non-hermetic fixture pointing at the live DB.
- **GAP-4 (WI4):** `document_embeddings.embedding` is **JSONB** (`0005:131`); `_score_documents`
  returns `keyword_overlap`; the `embedding_v1` branch is unused. pgvector extension not yet
  provisioned. Confirm Voyage model dims for the column width (D15).
- **GAP-5 (WI5):** only `InMemoryResponseCache` exists; determinism replay is in-process only.

---

## 7. Resolution protocol

Mirror Sprints 3–5: append numbered G-resolutions to a **§ Gap Resolutions** section here,
citing file/line. Do not silently change scope; flag any WI that turns out larger than scoped.

## 8. Definition of done

Sprint 6 is done when **all 7 cross-cutting items in §5 hold simultaneously on the live stack**.
The headline is a single live P-101A probe that is **safe (no live-store clobber), evidence-rich
(real CMMS WOs), specific (a real ISO mechanism), and semantically grounded (pgvector document
retrieval)** — materially better than the Sprint 5 probe, with cross-process determinism proven.

---

## § Gap Resolutions (Sprint 6 execution — code-true, file/line cited)

Per §7. Numbered continuation of the Sprint 3–5 G-series. Implemented on `feat/sprint-6`
(subagent-driven, two-stage review per task). Hermetic suite **616 passed / 17 skipped**; full
DB-gated suite **624 passed**; `ruff` + `mypy` clean (143 source files, with/without `[live]`).

- **G28 (WI1, D13 — alias schema differs from spec).** The spec assumed an alias lookup by
  `(source_system="maximo", asset_id)`. The live `asset_aliases` schema actually keys on
  **`connection_id`** (migration `0003_connections` superseded `0001`'s `source_system` column;
  ORM `mar/.../models.py:127-149`, repo `repository_pg.py:256` `source_handle_for(tenant, asset_id,
  connection_id)`). `MarAssetGateway` (`connector_sdk/.../assets.py`) therefore resolves
  `canonical_id → asset_id` (`find_asset_by_canonical_id`) → the **active** `(plant, "cmms")`
  connection (`list_connections(status="active")`) → `source_handle_for(...)`. Wired into the live
  work-order mount only (`agents/.../host.py`); hermetic tests keep the slug gateway. No new table.

- **G29 (WI4, D16 — no activation hook existed; documents have no version/hash).** Two spec
  assumptions were larger than the text implied:
  (a) `connections_api` activation was a bare status flip with **no event/hook**
  (`connections_router.py:197`). Added a symmetric, injectable, **no-op-default, failure-safe**
  `activation_listener` (fires on `/activate`) + `deactivation_listener` (fires on PATCH→disabled
  and DELETE) — preserving the "activation only writes the connections table" property by default.
  The live embedding listener (`agents/.../embedding_listener.py`,
  `build_document_embedding_listener`) runs the pipeline for `category=="document"` only;
  disconnect invalidates via `make_document_embedding_invalidator`. **Inline listener** chosen
  (owner decision) over a Temporal trigger.
  (b) `DocumentRef` carries no `version`/`hash`, so D16's version tagging uses a derived
  **`content_hash = sha256(connection_id:document_id:body)`** (body = title+excerpt, the
  deterministic source — the LLM `description` is excluded so the hash is a stable identity).
  **Remaining for the live §5 bar (CC5):** there is no `connections_api` *serving entrypoint*
  today (`create_app` is only called in tests); the live deployment must launch it with
  `activation_listener=build_document_embedding_listener(...)` +
  `deactivation_listener=make_document_embedding_invalidator(repo)`. The seam + listeners + pipeline
  are built and hermetically proven; only the live composition + run remain.

- **G30 (WI4, D15 — dims not env-configurable).** Added `rca_llm/embedding_config.py`
  (`EMBEDDING_MODEL` default `voyage-3`, `EMBEDDING_DIM` default `1024`). `HashEmbeddingTransport`
  now defaults to the configured dim so hermetic tests exercise the real `vector(1024)` query path;
  `LLMClient.embed` defaults its model to `embedding_model()`. The `vector(N)` column width is fixed
  at 1024 in migration `0007` and hardcoded in the ORM (`rca_mar` must not import `rca_llm`).

- **G31 (WI4/WI5 — migration chain).** Chain is `0006_asset_class_kg → 0007_pgvector_doc_embeddings
  → 0008_response_cache`, single head. `0007` provisions the `vector` extension, converts
  `document_embeddings.embedding` JSONB→`vector(1024)` (drop+re-add — a content-addressed cache,
  rows re-embed), adds `doc_type`/`description`/`connection_id` + an IVFFlat cosine ANN index.
  `0008` adds `response_cache`. Both idempotent (`IF [NOT] EXISTS`) and scoped to `rca_mar`
  (Temporal's `temporal`/`temporal_visibility` DBs untouched — Sprint 4 D3 re-verified). The
  IVFFlat index is untrained on an empty table (cosine queries fall back to seqscan until
  populated + `REINDEX`/`ANALYZE`) — documented inline in `0007`. **Live `rca_mar` is still at head
  `0006`** during development; applying `0007`/`0008` to the live store is part of CC5.

- **G32 (WI4 — `list_by_type` default `top=20` capped enumeration).** `document.list_by_type`
  defaults `top=20`, which would silently embed only the first 20 docs of a type on a larger plant.
  `McpDocSource.list_by_type` (`agents/.../doc_source.py`) passes `top=10_000` so the whole
  connected corpus is embedded.

- **G33 (WI3 carry-over, surfaced during WI5 — subprocess dropped the shared test DB).** WI3's
  `test_live_store_untouched.py` spawns a subprocess (`pytest test_migration_0003.py`) that reloaded
  the mar `conftest`, whose session-scoped fixture **DROPs the throwaway `test_rca_mar` on
  teardown** — destroying the *parent* session's shared DB and failing 8 mar DB tests under
  `RCA_DB=1`. Fixed by making the throwaway-DB name env-overridable (`MAR_TEST_DB`, default
  `test_rca_mar`); the subprocess now uses `test_rca_mar_subproc`. The WI5 cache DB tests were
  likewise isolated to `test_rca_cache`. `RCA_DB=1 uv run pytest packages/mar` → 98 passed; the
  full DB-gated suite → 624 passed; live `rca_mar` assets unchanged (proven by
  `test_live_store_untouched`).

### Cross-cutting status (§5 / §6)

- **§6 (the "implementation done" bar): DONE.** Hermetic suite green (616), full DB-gated suite
  green (624), `ruff`+`mypy` clean, pgvector migration applies to fresh DBs without breaking
  Temporal auto-setup, ~70 new tests added, no regressions.
- **§5 (the "live probe" bar): PENDING a live run (CC5).** WI1/WI2/WI4 acceptance is proven
  hermetically + via DB-gated tests; the headline live P-101A probe (real CMMS WOs + specific ISO
  mechanism + `embedding_v1` semantic retrieval + cross-process determinism, all on the live stack)
  requires: the simulators running, real LLM/Voyage keys, applying migrations `0007`/`0008` to the
  live `rca_mar`, and launching `connections_api` with the embedding listeners wired (G29). The
  cross-process determinism replay (§5.5) is already proven by a real two-subprocess test.
