# ADR-0012: Connectors own the contract; simulators stand in for sources

- **Status**: Accepted
- **Date**: 2026-06-04
- **Deciders**: gvishnu
- **Refines**: [ADR-0008 Simulators-first](0008-simulators-first.md)

## Context

[ADR-0008](0008-simulators-first.md) said "simulators expose the same MCP contract as production." That framing is wrong in a subtle but important way. It treats simulators as direct replacements for the MCP-facing surface, which would make the simulators themselves part of our long-term product surface area. They are not.

In our product there are three distinct things, and they have very different lifecycles:

| Layer | What it is | Who owns it | Lifecycle |
|---|---|---|---|
| **Source** | A real customer system (PI, Maximo, SAP, OPC, SharePoint, MQTT broker) | The customer / vendor | We do not touch |
| **Connector** | Our code that talks to a source on one side and exposes our canonical MCP contract on the other | **Us** | Long-lived, product code |
| **Simulator** | A fake source we run during dev/test/eval so connectors have something to talk to | **Us** | Internal-only, replaceable per-customer |

The **contract that matters** is **connector ↔ agent**. That contract is what we ship, what we test, what we version. Simulators sit *behind* connectors, on the source side, exactly where a real PI server or Maximo instance would sit. The connector code does not change when we point it at a simulator vs a real source.

## Decision

1. **Connectors are first-class product code.** One package per connector under `packages/connectors/` (e.g., `packages/connectors/pi/`, `packages/connectors/maximo/`). Each connector:
   - Talks to its source via the source's native protocol (PI Web API, Maximo OSLC, SAP PM RFC/OData, OPC UA, MQTT, SharePoint Graph).
   - Translates source-native data into our canonical Pydantic contracts.
   - Exposes an MCP server with our defined tool catalog (per [SPEC-002](../connectors/SPEC-002-mcp-tool-contracts.md)).
   - Owns its own retry, auth, rate-limiting, and provenance logic.

2. **Simulators replace sources, not connectors.** Each simulator implements the *source-side native protocol* — not our MCP contract. A PI simulator exposes PI Web API endpoints; the PI connector talks to it identically to how it talks to a real PI server. The Maximo simulator exposes OSLC; the Maximo connector talks to it the same way it talks to real Maximo.

3. **One contract, two paths to it.** The connector ↔ agent contract is the only thing the agent sees. Whether the connector is fronting a simulator or production is a configuration concern (env var pointing to a different host), not a code concern.

4. **Contract tests live at the connector boundary**, not the simulator boundary. We test that the connector produces valid Pydantic outputs given inputs from its source. The source can be a simulator (for CI) or a real instance (for parity tests).

## Diagram

```
┌─────────────────┐      ┌─────────────────────────────┐      ┌──────────────────┐
│  Real PI server │──────│                             │      │                  │
│  (customer)     │      │   PI Connector              │      │                  │
└─────────────────┘      │   (our code)                │──────│   Agent / MCP    │
                         │                             │ MCP  │   (our code)     │
┌─────────────────┐      │   - PI Web API client       │contract                  │
│  PI Simulator   │──────│   - canonical translation   │      │                  │
│  (our test code)│      │   - retry / auth / prov     │      │                  │
└─────────────────┘      └─────────────────────────────┘      └──────────────────┘
        ↑                              ↑                              ↑
   stands in for                  contract                        consumes
   the source side                lives HERE                      contract
   of the connector
```

## Alternatives considered

**A. Simulators expose MCP directly (original ADR-0008 framing).** Rejected. This means we never actually test the connector translation logic; "production-ready" demos run code that won't exist when a real customer plugs in. Whole class of bugs hide in the connector-to-source layer until pilot day.

**B. Skip simulators, mock the connectors instead.** Rejected. Mocked connectors drift from real connectors over time. The point of simulators is to exercise the **connector translation code** in dev and CI exactly as it runs in production.

**C. One connector binary that swaps mode (sim vs real) at runtime.** Rejected for clarity. Sim and real talk *to the same connector* via the same protocol; there's no mode switch inside the connector. The mode lives outside the connector, in deployment config.

## Consequences

**Positive:**

- The connector translation layer is exercised in dev, CI, and production. Same code path everywhere.
- Simulator-to-production swap is genuinely a config change (different host URL for the source).
- The contract surface area we ship is small and well-defined: `packages/contracts/` + connector MCP catalogs.
- Simulators can be deleted or replaced per customer without touching connector code or agent code.
- Connector code can be open-sourced or shared with partners independently of simulators (which contain our test IP).
- Each connector has clean ownership: one team, one code path, two deployment targets.

**Negative:**

- More code than the original simplification: a PI Web API client that we don't strictly need if simulators spoke MCP directly. But this is the *honest* amount of code; the original framing hid it.
- Simulators are now more complex — they must implement source-native protocols (PI Web API REST, Maximo OSLC, OPC UA stack). Building OPC UA in particular is non-trivial.
- We are coupled to the stability of source-side protocols (PI Web API versioning, OSLC profiles).

**Neutral:**

- Same number of MCP servers as before (one per connector), same MCP tool catalogs.
- Tenant onboarding workflow doesn't change.

## Implications for existing docs

- [ADR-0008](0008-simulators-first.md) supersedes-by-amendment: simulators stand in for sources, not for MCP servers. Patched.
- [SPEC-002](../connectors/SPEC-002-mcp-tool-contracts.md): tool catalogs are owned by connectors, not by simulators. Patched.
- [SPEC-007](../simulators/SPEC-007-simulator-behavior.md): simulators implement source-side protocols. Patched.
- [EPIC-002 Simulators](../simulators/EPIC-002-simulators.md): split. Simulators stay in EPIC-002 (build source-side fakes). A new [EPIC-013 Connectors](../connectors/EPIC-013-connectors.md) covers building the real connector code.

## References

- [ADR-0008 Simulators-first](0008-simulators-first.md) — original (amended)
- [SPEC-002 MCP Tool Contracts](../connectors/SPEC-002-mcp-tool-contracts.md)
- [SPEC-007 Simulator Behavior](../simulators/SPEC-007-simulator-behavior.md)
- [EPIC-013 Connectors](../connectors/EPIC-013-connectors.md)
