# Docs Index

Docs are organized by **workstream** — each folder contains the epic, specs, and explainers for that area. ADRs are cross-cutting and live in one place.

## Cross-cutting

- [PRIMER.md](PRIMER.md) — start here if you're new
- [PITFALLS_AND_RESOLUTIONS.md](PITFALLS_AND_RESOLUTIONS.md) — the 20 pitfalls and how the design resolves each
- [adrs/](adrs/) — 13 architecture decision records (ADR-0000 through ADR-0012)

## Workstreams

| Folder | What it covers | Key docs |
|---|---|---|
| [foundations/](foundations/) | Repo setup, contracts, evidence bundle, audit, onboarding | EPIC-000 roadmap, EPIC-001, SPEC-001, SPEC-009, SPEC-013, WEEK-1-QUICKSTART |
| [simulators/](simulators/) | **Track B** — source-side fakes for PI, Maximo, SAP, OPC UA, MQTT, SharePoint | EPIC-002, SPEC-007, SPEC-008, SPEC-014 |
| [connectors/](connectors/) | Real integration layer between MCP and source systems | EPIC-013, SPEC-002 |
| [mar/](mar/) | Master Asset Registry — canonical asset identity | EPIC-012, SPEC-011, how-mar-works |
| [trs/](trs/) | Tag Resolution Service — canonical signal identity (deferred — out of Phase 1) | EPIC-003, SPEC-003, how-trs-works |
| [templates/](templates/) | Equipment templates and overlay learning | EPIC-004, SPEC-010, SPEC-015 |
| [mcp/](mcp/) | MCP server tier registration and catalog | EPIC-005 |
| [temporal/](temporal/) | Probe workflow orchestration | EPIC-006, SPEC-004, SPEC-012 |
| [agents/](agents/) | LangGraph Tier 1-4 agents | EPIC-007, SPEC-006 |
| [hitl/](hitl/) | Human-in-the-loop UI and gates | EPIC-008, SPEC-005 |
| [eval/](eval/) | Replay runner + golden-set scoring | EPIC-009 |
| [observability/](observability/) | OTel, cost dashboard, HITL dashboard | EPIC-010 |
| [pilot/](pilot/) | Parity tests, runbook, acceptance gates | EPIC-011 |

## Quick navigation by role

- **Building a simulator (Track B)?** → [simulators/EPIC-002](simulators/EPIC-002-simulators.md) → [SPEC-014 fixture schema](simulators/SPEC-014-simulator-fixture-schema.md) → [SPEC-007 behavior](simulators/SPEC-007-simulator-behavior.md)
- **Building a connector (Track A)?** → [connectors/EPIC-013](connectors/EPIC-013-connectors.md) → [SPEC-002 tool contracts](connectors/SPEC-002-mcp-tool-contracts.md) → [ADR-0012](adrs/0012-connectors-own-the-contract.md)
- **Wiring contracts (Week 1)?** → [foundations/WEEK-1-QUICKSTART](foundations/WEEK-1-QUICKSTART.md) → [foundations/SPEC-001](foundations/SPEC-001-evidence-bundle.md)
- **Designing an agent?** → [agents/SPEC-006](agents/SPEC-006-agent-tier-graphs.md) → [temporal/SPEC-004](temporal/SPEC-004-probe-workflow.md)
