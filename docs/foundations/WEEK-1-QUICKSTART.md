# Week-1 Quick-Start: Exact files to create on day 1

**Note: TRS sections below are deferred — out of Phase 1 scope. See phase1_gap_analysis.md §8.**

**Audience**: the engineers who sit down Monday morning to start building.

**Goal of week 1**: kick off **both tracks in parallel**.
- **Track A (Product)**: `packages/contracts` published, docker-compose up (Postgres + Neo4j + Temporal + MinIO), Alembic migrations green, one passing contract test. **No agent code yet.** Contracts FIRST (closes gap G1).
- **Track B (Simulators)**: fixture loader + first two simulators (MQTT, OPC UA) running against the reference plant fixture. **Zero dependency on Track A.**

See [EPIC-000 Roadmap](EPIC-000-roadmap.md) for the two-track view.

This doc is opinionated and concrete. Deviate later if needed — but start here.

## Day-by-day plan (parallel tracks)

| Day | Track A (Product) | Track B (Simulators) |
|---|---|---|
| Mon | Repo bootstrapped with uv workspaces, `packages/contracts` skeleton, CI green | `packages/simulators/_fixture_loader/` + reference plant YAML drafted |
| Tue | All Pydantic contracts written (EvidenceBundle, AssetDescriptor, ProbeTrigger, …) | MQTT simulator publishing BIRTH + DATA against fixture |
| Wed | docker-compose stack up: Postgres, Neo4j, Temporal, MinIO; Alembic baseline | OPC UA simulator serving current values |
| Thu | `mar-service` + `trs-service` Postgres schemas migrated, first integration test (trs-service deferred — out of Phase 1) | Realism harness (clock skew, drops, latency) wired into both sims |
| Fri | One end-to-end contract test: serialize → write to Postgres → read → validate → equality | Both simulators reachable from compose; smoke test publishes/reads expected scenario events |

**The two tracks share nothing in week 1 except docker-compose.** Don't gate one on the other.

## Day 1 — Bootstrap (Monday)

### Files to create

```
rca_mvp/
├── pyproject.toml                       # uv workspace root
├── uv.lock
├── .python-version                      # 3.12
├── .gitignore
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── packages/
│   ├── contracts/
│   │   ├── pyproject.toml
│   │   ├── src/rca_contracts/
│   │   │   ├── __init__.py
│   │   │   ├── _ids.py                  # SignalID / AssetID / TenantID type aliases
│   │   │   ├── time_basis.py
│   │   │   ├── asset.py                 # AssetDescriptor
│   │   │   ├── signal.py                # SignalDescriptor
│   │   │   ├── measurement.py           # Measurement, MeasurementSeries
│   │   │   ├── alarm.py
│   │   │   ├── work_order.py
│   │   │   ├── document.py
│   │   │   ├── provenance.py
│   │   │   ├── evidence_bundle.py
│   │   │   ├── probe_trigger.py         # SPEC-012
│   │   │   ├── tool_error.py            # SPEC-002 error model
│   │   │   └── py.typed
│   │   └── tests/
│   │       └── test_roundtrip.py
│   └── common/
│       ├── pyproject.toml
│       └── src/rca_common/
│           ├── __init__.py
│           ├── ids.py                   # UUIDv7 generator
│           ├── time.py                  # UTC helpers, ISO 8601 parsing
│           └── logging.py
```

### Commands

```bash
# 1. Bootstrap
mkdir rca_mvp && cd rca_mvp
uv init --workspace
echo "3.12" > .python-version

# 2. Create packages
uv init --package packages/contracts
uv init --package packages/common
uv add --workspace pydantic uuid7 python-dateutil   # at workspace root

# 3. Dev tooling
uv add --dev ruff mypy pytest pytest-asyncio pytest-cov pre-commit
uv run pre-commit install

# 4. First test
uv run pytest packages/contracts -x

# 5. Push branch — CI should be green on empty repo
git checkout -b feat/bootstrap
git add . && git commit -m "bootstrap: uv workspaces, contracts skeleton"
```

### `pyproject.toml` (workspace root) — minimal

```toml
[project]
name = "rca-mvp"
version = "0.0.1"
requires-python = ">=3.12"

[tool.uv.workspace]
members = ["packages/*"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
strict = true
python_version = "3.12"
```

## Day 2 — Contracts (Tuesday)

**Goal**: every Pydantic class in [SPEC-001](SPEC-001-evidence-bundle.md), [SPEC-012](../temporal/SPEC-012-probe-trigger-schema.md), and [SPEC-002 ToolError](../connectors/SPEC-002-mcp-tool-contracts.md) implemented with frozen+strict+extra='forbid'. No business logic — pure data classes + validators.

### Acceptance criteria

- `from rca_contracts import EvidenceBundle, AssetDescriptor, ProbeTrigger, ToolError` works.
- `mypy --strict packages/contracts` passes.
- Round-trip test: `model.model_validate(model.model_dump()) == model` for every class.
- All timestamps are `AwareDatetime`; constructing with a naive datetime raises.
- `AssetDescriptor.tag` non-empty validator.
- `ProbeTrigger.model_validator` enforces window ordering (already in SPEC-012).

### Tip on UUIDv7

```python
# packages/common/src/rca_common/ids.py
from uuid_extensions import uuid7   # or roll your own; see RFC 9562 §5.7
__all__ = ["uuid7"]
```

## Day 3 — Infra (Wednesday)

### Files to create

```
infra/
├── docker/
│   ├── docker-compose.dev.yml
│   ├── postgres/init.sql              # CREATE EXTENSION pg_uuidv7, etc.
│   └── neo4j/init.cypher
├── temporal/
│   └── dynamicconfig/development-sql.yaml
└── README.md
```

### `docker-compose.dev.yml` (essentials)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: rca
    ports: ["5432:5432"]
    volumes:
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
  neo4j:
    image: neo4j:5.20-community
    environment:
      NEO4J_AUTH: neo4j/devpassword
    ports: ["7474:7474", "7687:7687"]
  temporal:
    image: temporalio/auto-setup:1.24
    environment:
      DB: postgres12
      DB_PORT: 5432
      POSTGRES_USER: postgres
      POSTGRES_PWD: dev
      POSTGRES_SEEDS: postgres
    ports: ["7233:7233"]
    depends_on: [postgres]
  temporal-web:
    image: temporalio/ui:2.27
    environment:
      TEMPORAL_ADDRESS: temporal:7233
    ports: ["8233:8080"]
    depends_on: [temporal]
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
```

### Commands

```bash
cd infra/docker
docker compose -f docker-compose.dev.yml up -d
docker compose ps     # all 5 services running
```

## Day 4 — Migrations (Thursday)

### Files to create

```
packages/mar/                            # Master Asset Registry service
├── pyproject.toml
├── src/rca_mar/
│   ├── __init__.py
│   ├── db.py                            # SQLAlchemy engine
│   └── models.py                        # ORM mapping AssetDescriptor → assets table
└── alembic/
    ├── env.py
    └── versions/
        └── 001_initial_mar.py

packages/trs/                            # Tag Resolution Service (deferred — out of Phase 1)
├── pyproject.toml
├── src/rca_trs/
│   ├── db.py
│   └── models.py                        # signals, signal_aliases, signal_alias_unresolved
└── alembic/
    └── versions/
        └── 001_initial_trs.py
```

DDL comes verbatim from SPEC-003 and SPEC-011 — copy and run.

### Acceptance

- `uv run alembic -c packages/mar/alembic.ini upgrade head` creates expected tables.
- Same for trs. (deferred — out of Phase 1)
- A pytest fixture spins up a fresh test DB per session and runs migrations.

## Day 5 — First contract test (Friday)

### What to write

`tests/contract/test_evidence_bundle_roundtrip.py`:

1. Build a synthetic `AssetDescriptor` and persist it into MAR (Postgres).
2. Build a `MeasurementSeries` (10 points, 1-minute interval) and persist its `EvidenceBundle` to MinIO.
3. Read both back; reconstruct full `EvidenceBundle`.
4. Assert `bundle == reconstructed` and `bundle.provenance != []`.
5. Negative: a bundle with a missing `asset_id` reference fails validation.

This single test exercises the whole week-1 surface. If it passes, the foundation is real.

## Track B — Simulator quickstart (parallel)

**Owner**: separate engineer; does not block on Track A.

### Files to create

```
fixtures/refplant/                       # see SPEC-014 for full schema
├── VERSION
├── plant.yaml
├── assets/{P-101A,P-101B,P-102A,P-103A}.yaml
├── signals/<asset>.<role>.yaml
├── scenarios/seal_leak_progression.yaml
└── time_axis.yaml

packages/simulators/
├── _fixture_loader/                    # day 1
│   ├── pyproject.toml
│   └── src/sim_fixtures/
│       ├── loader.py                   # YAML → pydantic
│       ├── trajectory.py               # baseline + scenario perturbation math
│       └── validate.py                 # CI validator from SPEC-014
├── _realism/                           # day 4
│   └── src/sim_realism/                # clock skew, drop, latency, error injection
├── mqtt_sparkplug/                     # day 2
│   └── src/sim_mqtt/
│       ├── broker.py                   # connects to Mosquitto in compose
│       └── publisher.py                # BIRTH at start, DATA at 1 Hz
└── opc_ua/                             # day 3
    └── src/sim_opc_ua/
        └── server.py                   # asyncua server mirroring AF hierarchy
```

### Compose additions (add to `docker-compose.dev.yml`)

```yaml
  mosquitto:
    image: eclipse-mosquitto:2
    ports: ["1883:1883"]
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf:ro

  sim-mqtt:
    build: ../../packages/simulators/mqtt_sparkplug
    depends_on: [mosquitto]
    environment:
      MQTT_BROKER: mosquitto:1883
      FIXTURE_PATH: /fixtures/refplant
    volumes:
      - ../../fixtures:/fixtures:ro

  sim-opc-ua:
    build: ../../packages/simulators/opc_ua
    ports: ["4840:4840"]
    environment:
      FIXTURE_PATH: /fixtures/refplant
    volumes:
      - ../../fixtures:/fixtures:ro
```

### Acceptance for Track B week 1

- [ ] `fixtures/refplant/` validates with `sim_fixtures.validate`.
- [ ] `docker compose up sim-mqtt mosquitto` runs; `mosquitto_sub -h localhost -t 'spBv1.0/#'` shows BIRTH then DATA.
- [ ] `docker compose up sim-opc-ua` runs; a sanity client (e.g., `opcua-client` GUI) connects to `opc.tcp://localhost:4840` and reads `P-101A.discharge_pressure`.
- [ ] Loading `scenarios/seal_leak_progression.yaml` produces a 30-day MQTT replay where vibration rises and a LEAK work-order event timestamp lines up with PI-side anomalies (verified by reading the fixture, not by querying Maximo yet).
- [ ] Realism harness env vars (`SIM_CLOCK_SKEW_SECONDS`, `SIM_DROP_RATE`) demonstrably change output.

**Track B is intentionally separate code; nothing here imports from `packages/contracts`.**

## Out of scope for week 1

- Any MCP server code (week 4 — part of EPIC-013)
- Any **connector** code (week 4 — EPIC-013)
- Any agent code (week 6+)
- Any TRS algorithm code (week 3) — only schemas this week
- PI / Maximo / SAP / SharePoint simulators (weeks 2–4 — still Track B, just later)

## Definition of done for week 1

### Track A
- [ ] `uv sync` from a clean checkout succeeds.
- [ ] `uv run pytest` passes (10+ contract tests).
- [ ] `uv run mypy --strict packages/contracts` passes.
- [ ] `docker compose up` brings the dev stack up (Postgres, Neo4j, Temporal, MinIO).
- [ ] Alembic migrations green on Postgres.
- [ ] One end-to-end roundtrip test green.
- [ ] CI green on `main`.

### Track B
- [ ] Fixture loader validates `fixtures/refplant/`.
- [ ] MQTT + OPC UA simulators run in compose.
- [ ] Realism harness wired and tested.
- [ ] One scenario (`seal_leak_progression`) replayable end-to-end through both simulators.

If you hit Friday and any **Track A** box is unchecked, **do not start week 2 on Track A** — finish the foundation first. Contracts drift is the single biggest risk in this product. Track B is independent — it can keep moving regardless.

## Next: Week 2

- **Track A**: [EPIC-012 MAR](../mar/EPIC-012-master-asset-registry.md) ingestion + [EPIC-003 TRS](../trs/EPIC-003-trs.md) schemas (deferred — out of Phase 1). Begin [EPIC-004 Templates](../templates/EPIC-004-templates.md) authoring.
- **Track B**: SharePoint/S3 simulator, then PI Web API. Aim to be code-complete on all six by end of week 4.
