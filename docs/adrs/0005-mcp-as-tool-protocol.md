# ADR-0005: MCP (Model Context Protocol) as the tool protocol

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

The agent invokes connectors (PI, Maximo, SAP, OPC, SharePoint, MQTT) and internal services (TRS, Templates, Knowledge Graph) through a uniform interface. We need a protocol that:

- Is supported by major LLM vendors (Anthropic, OpenAI, etc.) so we are not framework-locked.
- Allows clean separation between tool servers and tool clients.
- Supports typed schemas for inputs and outputs.
- Has reasonable local-dev ergonomics.

## Decision

Use **MCP (Model Context Protocol)** with **FastMCP** as the Python server framework.

- Each connector is an MCP server (`mcp_pi`, `mcp_maximo`, etc.) exposing a defined set of tools.
- Each internal service (TRS, Templates, KG) is also an MCP server.
- Simulators expose the *exact same MCP server contract* as production connectors. The agent does not know whether it is talking to a simulator or production. See [ADR-0008](0008-simulators-first.md).
- Tool inputs and outputs are Pydantic models from `packages/contracts`. FastMCP auto-generates JSON Schema from them.
- Tool catalogs are *bounded per tier*. The Scope-tier agent has access to the Scope toolset only.

## Alternatives considered

**A. OpenAI function-calling format only.** Rejected — couples us to one vendor's calling convention.

**B. LangChain tools.** Rejected — LangChain-specific, less interoperable, and the abstraction is thinner than MCP.

**C. Plain REST APIs with OpenAPI.** Viable but adds friction: the agent needs LLM-side function-calling shims for every endpoint. MCP unifies this.

**D. gRPC.** Rejected for tool layer — too low-level for LLM clients. We use gRPC internally where service-to-service performance matters.

## Consequences

**Positive:**

- Standard protocol; works with Anthropic, OpenAI, and the broader MCP ecosystem.
- Simulator-to-production swap is a single env-var change.
- Tool authoring is fast (FastMCP decorators).
- Tool catalogs per tier are enforced by which MCP servers are connected.

**Negative:**

- MCP is young; the spec is still evolving. We may need to absorb breaking changes.
- Streaming responses (e.g., long historian queries) require careful pagination.
- Local multi-server orchestration during dev requires docker-compose or equivalent.

## References

- MCP spec: https://modelcontextprotocol.io
- FastMCP: https://github.com/jlowin/fastmcp
- [SPEC-002 MCP Tool Contracts](../connectors/SPEC-002-mcp-tool-contracts.md)
