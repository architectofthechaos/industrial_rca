# ADR-0008: Simulators-first development with production-identical contracts

- **Status**: Accepted — **refined by [ADR-0012](0012-connectors-own-the-contract.md)**
- **Date**: 2026-06-03 (refined 2026-06-04)
- **Deciders**: gvishnu

> **Refinement note (ADR-0012):** Simulators do **not** expose MCP. They stand in for **sources** (PI Web API, OSLC, OPC UA, MQTT broker, SharePoint REST). **Connectors** are the product code that owns the MCP contract and talks to either a simulator or a real source. The original wording below ("Exposes the same MCP server contract as production") is superseded by this refinement — read it as "Exposes the same **source-side** protocol as production."

## Context

Getting access to a production PI server, Maximo instance, SAP PM, OPC server, etc. is slow, political, and customer-specific. We cannot wait for a pilot customer to start building. But we also cannot build the agent against fake interfaces that diverge from production — the day we plug into a real customer we will discover months of contract drift.

## Decision

Build simulators for all six MVP connectors **before** writing the agent. Each simulator:

1. **Exposes the same source-side protocol as production.** A simulator pretends to be PI Web API, an OSLC server, an OPC UA endpoint, an MQTT broker, or a SharePoint REST API. **Connectors** (product code, see ADR-0012) sit in front of simulators in dev and real sources in production. The agent talks to connectors via MCP and does not know whether the source behind a connector is real or simulated.
2. **Returns realistic data for a centrifugal pump reference plant.** Seed dataset includes:
   - A simulated plant with hierarchy: Site → Area → Unit → Equipment (with at least 4 centrifugal pumps in different services: charge pump, BFW pump, injection pump, transfer pump)
   - 6+ months of historian data with realistic patterns and embedded failure events
   - Maximo work orders, notifications, failure history matching the historian events
   - Operator narratives, RCA reports, datasheets as documents in SharePoint
   - OPC UA real-time data feed at 1 Hz
   - MQTT Sparkplug B publication
3. **Includes a scenario catalog.** Each scenario is a known failure with known evidence:
   - `seal_leak_progression` — slow seal degradation over 30 days
   - `cavitation_event` — sudden NPSH loss
   - `bearing_failure` — vibration progression to trip
   - `motor_trip_overload` — electrical fault
   - These are the seed for the evaluation harness ([EPIC-008](../../eval/EPIC-009-evaluation-harness.md)).
4. **Contract-tested.** Every simulator response is validated against the same Pydantic models as production. Contract tests run in CI.
5. **Configurable behavior:** simulators can inject realistic failures — clock skew, dropped messages, slow responses, partial data, missing units — so the agent is hardened to messy reality.

## Alternatives considered

**A. Build agent first against mocked tool responses.** Rejected — mocks drift from real contracts, hardening against real-world messiness happens too late.

**B. Use vendor sandboxes (PI System Explorer demo, IBM Maximo trial).** Rejected — license-restricted, scenario-poor, not parameterizable, often unavailable offline.

**C. Skip simulators, build only the 3 core (PI, Maximo, SharePoint) and add others later.** Rejected — UNS via MQTT Sparkplug B and OPC UA are differentiators for our wedge; building them at the same time exercises the multi-source join logic that is the hardest part of the system.

## Consequences

**Positive:**

- Agent development is unblocked from customer access.
- The simulator-to-production swap is a config change, not a code change.
- Scenarios become regression tests — every time the agent improves, we can rerun all scenarios and verify outcomes.
- Pilot rollouts have a known baseline of agent behavior.
- Demos to prospects run on simulators with predictable outcomes.

**Negative:**

- Building 6 simulators is non-trivial work — estimated 4–6 weeks for a pair of engineers.
- Simulators can lie about reality if our model of real systems is wrong; we must validate against at least one real customer connection before claiming production parity.
- Maintenance burden — when a production connector's contract changes, the simulator must update too.

## References

- [SPEC-007 Simulator Behavior](../simulators/SPEC-007-simulator-behavior.md)
- [SPEC-008 Scenario Catalog](../simulators/SPEC-008-scenario-catalog.md)
- [EPIC-002 Simulators](../simulators/EPIC-002-simulators.md)
