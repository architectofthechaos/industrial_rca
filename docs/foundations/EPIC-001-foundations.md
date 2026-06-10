# EPIC-001: Foundations

**Goal**: Repo skeleton, contracts, infra. Everything else depends on this landing first.

**Duration**: Week 1–2

## Stories

### S1.1 — Monorepo bootstrap
- Initialize uv workspace at repo root.
- Create `pyproject.toml` per package, declare workspace membership.
- Configure ruff, mypy, pytest, pre-commit.
- CI: lint + type-check + test on every PR.

**DoD**: `uv sync` works; `uv run pytest` runs (empty) tests across all packages.

### S1.2 — Contracts package
- Implement all Pydantic models per [SPEC-001 Evidence Bundle](SPEC-001-evidence-bundle.md) and SPEC-002 inputs/outputs.
- Strict mode, frozen, extra='forbid'.
- AwareDatetime validator that rejects naive.
- Unit tests for every model: valid + invalid cases.

**DoD**: 100% of contracts in SPEC-001 and SPEC-002 implemented; tests pass; JSON Schema export verified.

### S1.3 — Common utilities
- `common.time` — UTC helpers, timedelta parsing.
- `common.units` — QUDT URIs, Pint integration, conversion with explicit ambiguity errors.
- `common.ids` — UUIDv7 generator for SignalIDs and probe IDs.
- `common.logging` — structured JSON logging with `probe_id`, `tenant_id`, `tier`, `tool` context.
- `common.tracing` — OpenTelemetry initialization.

**DoD**: Used by at least two other packages.

### S1.4 — Infra docker-compose
- Postgres (TRS, audit log, app)
- Neo4j (KG)
- MinIO (S3-compatible object storage)
- Temporal cluster (frontend, history, matching, worker)
- Optional: Jaeger for traces, Grafana for metrics

**DoD**: `docker compose up` brings the full local dev stack online; smoke test connects to each.

### S1.5 — Postgres migrations
- TRS schema (`signals`, `signal_aliases`, `signal_alias_unresolved`).
- Audit log schema (partitioned by month).
- Ops schema (`probes`, `templates_loaded`, `hitl_requests`, `overlay_updates`).
- Alembic migrations.

**DoD**: Migrations apply cleanly to empty Postgres; rollbacks tested.

## Out of scope

- Production deployment (Phase 4).
- Auth / multi-tenancy enforcement (Phase 4; tenant_id stubs added now).
