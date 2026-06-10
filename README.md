# RCA MVP

Probe-based root cause analysis for industrial assets. ISO 14224 grounded. Builds the plant knowledge graph one probe at a time.

## What this repo is

This is the implementation MVP for the architecture covered in the recap deck. We are building a generic product (not customer-specific) anchored to **centrifugal pump** as the reference equipment class. Other classes follow the same patterns.

## Critical design decisions (read before coding)

| Concern | Decision | Reference |
|---|---|---|
| Workflow engine | **Temporal** | [ADR-0003](docs/adrs/0003-workflow-engine-temporal.md) |
| Agent framework | **LangGraph** inside Temporal activities | [ADR-0004](docs/adrs/0004-agent-framework-langgraph.md) |
| Tool protocol | **MCP** (FastMCP) | [ADR-0005](docs/adrs/0005-mcp-as-tool-protocol.md) |
| Asset canonicalization | **Master Asset Registry** — Asset IDs everywhere, source IDs as aliases | [ADR-0011](docs/adrs/0011-master-asset-registry.md) |
| Tag canonicalization | **Signal IDs everywhere**, no raw tags reach agent | [ADR-0001](docs/adrs/0001-tag-resolution-service.md) |
| Units of measure | **QUDT** ontology, canonical SI internally | [ADR-0002](docs/adrs/0002-units-of-measure.md) |
| Time | **UTC ISO 8601 everywhere**, explicit time_basis | [ADR-0006](docs/adrs/0006-time-handling.md) |
| Contracts | **Pydantic v2** as source of truth | [ADR-0007](docs/adrs/0007-contracts-as-pydantic.md) |
| Connectors | **Connectors own the MCP contract**; simulators stand in for sources | [ADR-0012](docs/adrs/0012-connectors-own-the-contract.md) |
| Simulators | **Stand in for source systems** (PI Web API, OSLC, OPC UA, MQTT, SharePoint REST) | [ADR-0008](docs/adrs/0008-simulators-first.md) |
| Repo style | **Monorepo with uv workspaces** | [ADR-0009](docs/adrs/0009-monorepo-uv-workspaces.md) |
| Provenance | **Every tool return carries a provenance block** | [ADR-0010](docs/adrs/0010-provenance-and-audit.md) |

## Repo layout

```
rca_mvp/
├── docs/
│   ├── INDEX.md           Workstream map (start here)
│   ├── PRIMER.md          Narrative intro for new contributors
│   ├── PITFALLS_AND_RESOLUTIONS.md
│   ├── adrs/              Architecture Decision Records (cross-cutting, immutable)
│   ├── foundations/       EPIC-000, EPIC-001, SPEC-001, SPEC-009, SPEC-013, WEEK-1-QUICKSTART
│   ├── simulators/        EPIC-002, SPEC-007, SPEC-008, SPEC-014  (Track B)
│   ├── connectors/        EPIC-013, SPEC-002  (Track A integration layer)
│   ├── mar/               EPIC-012, SPEC-011, how-mar-works
│   ├── trs/               EPIC-003, SPEC-003, how-trs-works
│   ├── templates/         EPIC-004, SPEC-010, SPEC-015
│   ├── mcp/               EPIC-005
│   ├── temporal/          EPIC-006, SPEC-004, SPEC-012
│   ├── agents/            EPIC-007, SPEC-006
│   ├── hitl/              EPIC-008, SPEC-005
│   ├── eval/              EPIC-009
│   ├── observability/     EPIC-010
│   └── pilot/             EPIC-011
├── packages/
│   ├── contracts/   Pydantic models — the single source of truth for all interfaces
│   ├── common/      Shared utilities — UUIDs, time, units, logging, tracing
│   ├── templates/   Equipment-class YAML templates (centrifugal_pump.yaml is the reference)
│   ├── mcp_server/  FastMCP servers that expose tools by tier (Scope/Evidence/Reason/Govern)
│   ├── workflows/   Temporal workflows + activities, one per tier
│   ├── agent/       LangGraph agent definitions invoked inside Temporal activities
│   ├── connectors/   Product code — MCP servers translating to source-side protocols
│   │   ├── pi/                  # PI Web API REST
│   │   ├── maximo/              # OSLC REST
│   │   ├── sap_pm/              # OData v2
│   │   ├── opc_ua/              # OPC UA binary
│   │   ├── documents/           # SharePoint Graph / S3
│   │   └── mqtt_uns/            # MQTT + Sparkplug B
│   ├── connector_sdk/  Shared SDK: provenance, units, time, errors, retries, validation
│   ├── simulators/   Source-side fakes (dev/CI only — NOT shipped to customers)
│   │   ├── pi_historian/        # PI Web API REST subset
│   │   ├── maximo/              # OSLC REST subset
│   │   ├── sap_pm/              # OData v2 subset
│   │   ├── opc_ua/              # asyncua server
│   │   ├── sharepoint_s3/       # HTTP REST / S3
│   │   └── mqtt_sparkplug/      # Mosquitto + publisher
│   └── evaluation/  Frozen probes with known outcomes, eval harness
├── infra/
│   ├── temporal/    Temporal docker-compose, namespaces, retention policies
│   ├── postgres/    Migrations, schemas (ops, audit)
│   ├── neo4j/       Graph constraints, indexes
│   └── docker/      Top-level compose for local dev
├── scripts/         Dev tooling (seed simulators, run a probe, replay eval set)
└── tests/
    ├── contract/    Contract tests — simulator returns must match Pydantic schema
    ├── integration/ End-to-end tier flows against simulators
    └── e2e/         Full probe lifecycle, including HITL
```

## Where to start reading

**For understanding** (narrative, written like a walkthrough):
1. [Explainers](docs/PRIMER.md) — start here if you're new
2. [How MAR works](docs/mar/how-mar-works.md)
3. [How TRS works](docs/trs/how-trs-works.md) (deferred)

**For decisions and reference**:
4. Pillar ADRs — [0012 Connectors own the contract](docs/adrs/0012-connectors-own-the-contract.md), [0011 MAR](docs/adrs/0011-master-asset-registry.md), [0001 TRS](docs/adrs/0001-tag-resolution-service.md), [0002 Units](docs/adrs/0002-units-of-measure.md), [0003 Temporal](docs/adrs/0003-workflow-engine-temporal.md), [0006 Time](docs/adrs/0006-time-handling.md)
5. [SPEC-001 Evidence Bundle](docs/foundations/SPEC-001-evidence-bundle.md) — the fundamental data structure (now includes `AssetDescriptor`)
6. [SPEC-002 MCP Tool Contracts](docs/connectors/SPEC-002-mcp-tool-contracts.md) — connectors own these tools
7. [SPEC-012 Probe Trigger Schema](docs/temporal/SPEC-012-probe-trigger-schema.md), [SPEC-013 Tenant Onboarding](docs/foundations/SPEC-013-tenant-onboarding.md), [SPEC-014 Simulator Fixture Schema](docs/simulators/SPEC-014-simulator-fixture-schema.md), [SPEC-015 Equipment Template Schema](docs/templates/SPEC-015-equipment-template-schema.md)
8. [EPIC-001 Foundations](docs/foundations/EPIC-001-foundations.md) and [EPIC-013 Connectors](docs/connectors/EPIC-013-connectors.md)

**For implementation (start here Monday)**:
- [WEEK-1 Quick-Start](docs/WEEK-1-QUICKSTART.md) — day-by-day day 1–5 plan
- [PROGRESS.xlsx](PROGRESS.xlsx) — live progress tracker (8 sheets: Dashboard, Burn-up, Track A, Track B, Blockers, Decisions, Gaps, Lessons). Status dropdowns auto-color; epic rollups auto-compute.

## Mental model: Agent ↔ Connector ↔ Simulator/Source

```
  Agent  ──MCP──▶  Connector (product code)  ──source protocol──▶  Simulator  OR  Real source
                                                                  (dev/CI)         (prod)
```

The MCP contract is invariant across the simulator↔production swap. **Connectors ship; simulators do not.** See [ADR-0012](docs/adrs/0012-connectors-own-the-contract.md).

## Status

- [x] Architecture defined (recap deck)
- [x] ADRs drafted
- [x] Specs drafted
- [x] Epics broken into stories
- [ ] Contracts implemented (Pydantic models)
- [ ] TRS service implemented (deferred — out of Phase 1)
- [ ] Simulators built
- [ ] Temporal workflows implemented
- [ ] LangGraph agents implemented
- [ ] First end-to-end probe against simulators
- [ ] Evaluation harness with 10 frozen probes
- [ ] First pilot
