# Sprint 6 State Report — Evidence Quality, Test Safety & Semantic Document Search

> **Branch:** `feat/sprint-6` off `main` (`7e7296a`), HEAD `df3619e` (32 commits). **Status:**
> all 5 WIs implemented; the **§6 implementation bar is DONE** (hermetic + full DB-gated suites
> green, lint clean, pgvector migration Temporal-safe, no regressions). The **§5 live-probe bar is
> PENDING a live run (CC5)** — see "Remaining for the live bar". Spec + G-resolutions:
> `sprint6_spec.md` § Gap Resolutions (G28–G33). Plan: `docs/superpowers/plans/2026-06-12-sprint-6.md`.

## Headline

The probe is now built to be **safe, evidence-rich, specific, and semantically grounded**:
a MAR-backed gateway resolves the Maximo location so CMMS work-order evidence is no longer skipped;
per-probe GraphRAG feeds the rank prompt the class-scoped ISO mechanism vocabulary so the LLM picks
a specific mechanism instead of the `other` fallback; the destructive migration test can no longer
clobber the live `rca_mar` store; documents are embedded into a pgvector `vector(1024)` column on
`document`-connection activation and gather scores them by cosine similarity (`embedding_v1`); and
a `PostgresResponseCache` makes determinism replay work across processes (proven by a real
two-subprocess test). Every WI was executed subagent-driven with a two-stage (spec → code-quality)
review per task.

## Work items

| WI | Decision | Outcome |
|---|---|---|
| **WI1 — CMMS evidence** | D13 — MAR-backed asset gateway | ✅ `MarAssetGateway` resolves `canonical_id → asset_id → active cmms connection → maximo location` via MAR aliases; wired into the live work-order mount (slug gateway elsewhere). Alias keys on `connection_id`, not `(source_system, asset_id)` — **G28**. |
| **WI2 — specific mechanisms** | D14 — GraphRAG vocab | ✅ Gather queries `kg.list_failure_modes_for_class` and carries the `CAUSED_BY` mechanisms into the Evidence Package; the `rca_rank_hypotheses` prompt gets `kg_valid_mechanisms`; out-of-vocab LLM choices coerce to `failure-mechanism:other` (G26 invariant preserved). |
| **WI3 — test safety** | carry-over | ✅ `assert_test_database` guard + a session-autouse redirect isolate **all** mar DB tests to a throwaway `test_rca_mar`; the destructive `downgrade base`/`DELETE` can never hit the live store (proven: live assets unchanged across a full DB-gated run). A subprocess self-collision was found + fixed — **G33**. |
| **WI4 — pgvector semantic search** | D15/D16/D17 | ✅ Migration `0007` (extension + `vector(1024)` + `doc_type`/`description`/`connection_id` + IVFFlat cosine index); env-configurable model/dim (**G30**); `DocumentEmbeddingPipeline` (enumerate→summarize→embed→upsert); inline activation/deactivation listeners (**G29**); semantic `_score_documents` (`embedding_v1`) with keyword fallback, demonstrated as a genuine keyword→semantic **rank reversal**; `top` cap fixed (**G32**). |
| **WI5 — Postgres response cache** | closes Sprint 4/5 deferral | ✅ Migration `0008` (`response_cache`) + `PostgresResponseCache` (mirrors `PostgresLlmAuditSink`); lazily wired into `deps.build_llm` (hermetic `import rca_llm` pulls no asyncpg). Cross-process determinism proven by **two real subprocesses** replaying byte-identically from the shared cache. |

## Gap resolutions

G28–G33 are in `sprint6_spec.md` § Gap Resolutions with file/line citations. One line each:

- **G28** alias table keys on `connection_id` (0003 superseded 0001's `source_system`); gateway resolves via the active cmms connection.
- **G29** no activation hook existed → added no-op-default, failure-safe `activation_listener`/`deactivation_listener` seams + the embedding listener/invalidator; `content_hash` = sha256(connection_id:document_id:body) (docs carry no version). Live serving-entrypoint wiring remains for CC5.
- **G30** added `EMBEDDING_MODEL`/`EMBEDDING_DIM` config; `HashEmbeddingTransport` matches the column dim.
- **G31** chain `0006→0007→0008`, idempotent + Temporal-safe; live still at `0006` (apply at CC5).
- **G32** `McpDocSource` passes `top=10_000` (the `list_by_type` default `top=20` would silently cap embedding).
- **G33** `test_live_store_untouched`'s subprocess dropped the shared `test_rca_mar` (8 failures under `RCA_DB=1`); fixed via env-overridable `MAR_TEST_DB` (+ WI5 cache tests isolated to `test_rca_cache`).

## Verification

- **Hermetic:** `uv run pytest -q` → **616 passed / 17 skipped** (was 550/11 at Sprint 5; ~70 new
  regression + WI tests). `ruff` clean; `mypy` clean across `*/src` (143 files), with and without
  the `rca-llm[live]` extra.
- **DB-gated (live Postgres up):** `RCA_DB=1 uv run pytest -q` → **624 passed / 9 skipped**
  (skips are the `RCA_STACK`-gated live tests). All DB tests run against throwaway `test_*`
  databases; `RCA_DB=1 uv run pytest packages/mar` → 98 passed.
- **pgvector migration:** applies cleanly to a fresh `test_rca_mar` (extension, `vector(1024)`,
  IVFFlat index), idempotent (downgrade/upgrade verified); does NOT break Temporal auto-setup
  (separate DBs).
- **Live store safety:** `test_live_store_untouched` (stack-gated) confirms the live `rca_mar`
  asset count is unchanged across the destructive test; live store remains at head `0006`.

## Remaining for the live bar (§5 / CC5)

The implementation is complete and hermetically proven; the headline **live P-101A probe** needs a
live run that is environment + cost gated:

1. **Apply migrations `0007`/`0008` to the live `rca_mar`** (`alembic upgrade head`).
2. **Launch `connections_api` with the embedding listeners wired** (G29): no serving entrypoint
   exists today (`create_app` is test-only) — compose it with
   `activation_listener=build_document_embedding_listener(doc_client, llm, repo, embed_transport=VoyageEmbeddingTransport())`
   and `deactivation_listener=make_document_embedding_invalidator(repo)`.
3. **Run the full P-101A probe** with the simulators + real Anthropic/Voyage keys and assert §5:
   CMMS coverage `ok` (record_count > 0), `primary_hypothesis.iso14224_mechanism != other`,
   `document_evidence.score_method == "embedding_v1"` with the prior RCA out-ranking a keyword-only
   match, and cross-process determinism replay. Capture the run in
   `docs/pilot/sprint6_live_validation.md` (mirror Sprint 5's WI1 record).

## Deferred / follow-ups (non-blocking)

- Consolidate the per-component MAR engines (audit sink, cache, repos each `make_engine()`) behind
  a shared engine/pool (minor resource note; pre-existing pattern).
- IVFFlat `REINDEX`/`ANALYZE` once the embedding cache is populated (recall is exact-but-unindexed
  until then — documented in `0007`).
