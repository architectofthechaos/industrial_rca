# EPIC-000: Roadmap

12-week MVP plan. **Two parallel tracks** — the simulator track is independent of everything else and can finish on its own clock.

## The two tracks

```
                  week:  1   2   3   4   5   6   7   8   9   10  11  12
TRACK A (Product)        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Contracts              ████
  MAR + TRS                  ████████
  Templates                  ████████
  connector_sdk                    ████
  Connectors                            ████████████
  Temporal + LangGraph                          ████████████
  HITL UI                                       ████████████
  Eval + Observability                                  ████████
  Pilot prep                                                        ████

TRACK B (Test infra)     ━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Fixture loader         ████
  Simulator x 6          ████████████████████
  Realism harness                ████████
  (joins Track A here)                       │
                                             ▼
                                       Connector contract tests against simulators
```

**Track B has no upstream dependencies inside this repo.** Simulators talk source-side protocols (PI Web API, OSLC, OData, OPC UA, MQTT, SharePoint REST) and read YAML fixtures. They don't need contracts, MAR, TRS, or connector_sdk to exist. A separate engineer can finish all 6 by week 4 and Track A consumes them when ready.

## Track A — Product code (dependency-ordered)

### Phase 1 — Foundations (weeks 1–2)
- [EPIC-001 Foundations](EPIC-001-foundations.md): contracts, monorepo, infra, migrations

### Phase 2 — Core services (weeks 2–5)
- [EPIC-012 Master Asset Registry](EPIC-012-master-asset-registry.md): identity + hierarchy. **Must precede TRS.**
- [EPIC-003 TRS](EPIC-003-trs.md): depends on MAR (`signals.asset_id` FK to `assets`)
- [EPIC-004 Templates](EPIC-004-templates.md): centrifugal pump reference

### Phase 3 — Connectors (weeks 4–6)
- [EPIC-013 Connectors](EPIC-013-connectors.md): `connector_sdk` first (week 4), then 6 connectors in parallel (weeks 5–6)
- Each connector consumes its matching Track B simulator for contract tests

### Phase 4 — Workflow + agent (weeks 6–9)
- [EPIC-005 MCP Servers](EPIC-005-mcp-servers.md): tier-aware MCP server registration (mostly assembly at this point)
- [EPIC-006 Temporal Workflows](EPIC-006-temporal-workflows.md)
- [EPIC-007 LangGraph Agents](EPIC-007-langgraph-agents.md)
- [EPIC-008 HITL UI](EPIC-008-hitl-ui.md)

### Phase 5 — Quality + pilot prep (weeks 10–12)
- [EPIC-009 Evaluation Harness](EPIC-009-evaluation-harness.md)
- [EPIC-010 Observability](EPIC-010-observability.md)
- [EPIC-011 Pilot Readiness](EPIC-011-pilot-readiness.md)

## Track B — Simulators (weeks 1–4, fully parallel)

- [EPIC-002 Source Simulators](EPIC-002-simulators.md). Six simulators + shared fixture loader + realism harness.
- **No dependency on Track A.** Can be started day 1 by anyone with `docker`, Python, and the source-protocol libraries (`fastapi`, `asyncua`, `paho-mqtt`, `minio`).
- **One sync point with Track A**: when `connector_sdk` lands in week 4, connector engineers point at the matching simulator endpoints and run contract tests. If the simulator is finished, the contract test is the first piece of agent-facing code to ever exercise it.

## Critical path

```
Contracts → MAR → TRS → connector_sdk → Connectors → Workflows + Agent → Eval → Pilot
                                            ▲
                                            │ (simulators ready by here, on a parallel clock)
```

**Simulators are NOT on the critical path.** They are gating only for *contract tests*, not for shipping. If a real-source dev image (e.g., OSIsoft PI Web API demo) is available for a given connector, that connector can skip its simulator entirely.

## Parallelism summary

| Can run in parallel | Why |
|---|---|
| All 6 simulators with each other | Different processes, different protocols, shared fixture only |
| All of Track B with all of Track A | No shared code |
| MAR and Templates | Both depend only on contracts |
| All 6 connectors with each other (after connector_sdk) | Different upstream protocols, same SDK |
| HITL UI and Eval Harness | Both depend only on contracts + Temporal |

## Staffing implication

- **1 engineer** dedicated to Track B for weeks 1–4 (then rolls into Track A connector work). Could be a contractor or junior — fixture-driven simulators are mechanical.
- **2–3 engineers** on Track A for the full 12 weeks. They never wait on simulators.
