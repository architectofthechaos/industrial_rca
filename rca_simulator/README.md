# rca_simulator

Source-side **simulators** for the RCA MVP — Track B, [EPIC-002](../docs/simulators/EPIC-002-simulators.md).
**Internal dev/CI only. Not shipped to customers.**

## What this is

Each simulator stands in for a real upstream **source** system and speaks that
system's *native protocol*. Connectors (product code, [EPIC-013](../docs/connectors/EPIC-013-connectors.md))
sit in front of these in dev and in front of real sources in production — the
swap is a config change, not a code change ([ADR-0012](../docs/adrs/0012-connectors-own-the-contract.md)).

```
Agent ──MCP──▶ Connector (ships) ──source protocol──▶ rca_simulator (dev/CI) | Real source (prod)
```

### Hard rules (ADR-0012 / EPIC-002)

- Simulators speak source-native protocols, **never MCP**.
- Simulators **do NOT import** product code (`packages/contracts`, MAR, TRS, `connector_sdk`).
- All output derives from the shared `fixtures/refplant/` tree, so every source is coherent.
- Synthesis + realism are **deterministic when seeded**.

## Layout

```
rca_simulator/
├── pyproject.toml              # uv/hatchling package (rca-simulator)
├── .python-version             # 3.12
├── docker-compose.yaml         # local dev stack (broker + sims + MinIO)
├── rca_simulator/              # the importable package (flat layout)
│   ├── fixtures/               # S2.1  shared fixture schema/loader/expander/validator  [BLOCKER]
│   ├── realism/                # S2.8  realism-injection harness (imported by all sims)
│   ├── pi/                     # S2.2  PI Historian        (PI Web API REST)
│   ├── maximo/                 # S2.3  Maximo              (OSLC REST)
│   ├── sap_pm/                 # S2.4  SAP PM             (OData v2)
│   ├── opcua/                  # S2.5  OPC UA             (asyncua server)
│   ├── documents/              # S2.6  SharePoint / S3    (Graph + Search REST)
│   └── mqtt/                   # S2.7  MQTT Sparkplug B   (broker + publisher)
├── fixtures/
│   └── refplant/               # the shared source of truth (see SPEC-014)
│       ├── VERSION
│       ├── plant.yaml
│       ├── time_axis.yaml
│       ├── assets/             # P-101A, P-101B, P-102A, P-103A
│       ├── signals/            # <asset>.<role>.yaml
│       ├── scenarios/          # seal_leak / cavitation / bearing / motor_trip
│       ├── work_orders/        # baseline historical seeds
│       └── documents/          # datasheets / pids / rca_reports
└── tests/                      # one test module per simulator + fixtures + realism
```

Each subpackage's `__init__.py` documents its modules and the task it implements, and each
**simulator has its own `README.md`** with the endpoints/topics it exposes and how to connect:
[pi](rca_simulator/pi/README.md) · [maximo](rca_simulator/maximo/README.md) ·
[sap_pm](rca_simulator/sap_pm/README.md) · [opcua](rca_simulator/opcua/README.md) ·
[documents](rca_simulator/documents/README.md) · [mqtt](rca_simulator/mqtt/README.md).

## Status

**All tasks implemented (S2.1–S2.8) — 131 unit tests passing, ruff clean.** Built test-first.
Per-task suites live in `tests/`; `tests/test_cross_source_coherence.py` asserts PI, Maximo,
and SAP all describe the same scenario on one timeline.

**Live smoke test (`task smoke`)** drives all six sims over their real wire protocols against
the running stack (HTTP for PI/Maximo/SAP/Docs, an OPC UA client, and a Sparkplug B subscriber
on the MQTT broker). Verified end-to-end via `task up` → `task smoke` (6/6) → `task down`.
BIRTH messages are retained, so a connector joining mid-stream still resolves aliases.

Still not exercised by any test (low risk, deferred to EPIC-013 connectors): OPC UA
*subscriptions* (smoke does a read, not a subscribe) and the S3/MinIO document variant.

## Build order

| Phase | Tasks | Why |
|---|---|---|
| 1 | **S2.1** fixtures + **S2.8** realism | Everything depends on these. Build/verify first. |
| 2 | S2.7 MQTT, S2.5 OPC UA | Simplest real protocols; prove the foundation. |
| 3 | S2.6 documents, S2.2 PI | Higher surface area (PI `mode` semantics). |
| 4 | S2.3 Maximo, S2.4 SAP PM | CMMS; SAP deliberately diverges from Maximo. |

Full task detail: [TASKS-EPIC-002](../docs/simulators/TASKS-EPIC-002.md).
Implementation plan: [PLAN-EPIC-002-implementation](../docs/simulators/PLAN-EPIC-002-implementation.md).

## Dev quickstart (once tasks are implemented)

```bash
uv sync                                   # install deps
uv run pytest                             # run simulator test suites
docker compose up -d                      # bring up the source stack locally
```

## Open structure decisions

- `fixtures/refplant/` currently lives inside this app folder for self-containment.
  SPEC-014 / Week-1 examples place it at repo root and mount `../../fixtures`.
  Revisit if/when this folds into a top-level uv workspace (ADR-0009).
