# ADR-0003: Temporal as the workflow engine

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

A probe is a long-running, multi-step process:

- Duration ranges from minutes (cached evidence, clear cause) to days (waiting on lab results or HITL approval).
- Mixes deterministic steps (tool calls, validations) with non-deterministic steps (LLM reasoning).
- Has multiple human-in-the-loop gates (tag confirmation, cause map approval, CMMS write-back authorization).
- Must survive process crashes, deployments, and infrastructure restarts.
- Must be auditable for every step — what was called, with what inputs, what was returned, what was decided.
- Workflow definitions evolve; in-flight probes must keep their original definition; reopened probes must resume on a version-pinned graph.

LangGraph alone gives us a graph runtime with checkpointing but lacks production-grade retries, signals, versioning, observability, and operational tooling.

## Decision

We will use **Temporal** (https://temporal.io) as the durable workflow engine.

- Each tier (Scope / Evidence / Reason / Govern) is a Temporal **workflow**.
- The Probe Orchestrator is a parent workflow that starts the tier workflows and aggregates their state.
- MCP tool invocations happen inside Temporal **activities** with explicit retry policies.
- Agent reasoning (LangGraph graph execution) runs inside a long-running activity, with checkpoints persisted to Temporal payload storage.
- HITL gates use Temporal **signals** — the workflow `await_signal('hitl_response', ...)` and survives any process restart.
- Workflow definitions are **versioned** with `workflow.get_version()`; in-flight probes pin to their original version.
- Self-hosted Temporal cluster on Postgres for MVP. Temporal Cloud is an option for scale.

## Alternatives considered

**A. Restate.dev.** Smaller community but cleaner API for durable functions. Rejected for MVP because Temporal has more mature operational tooling (Web UI, replay, signals, schedules), better Python SDK, and more battle-tested HITL patterns. Revisit in v2 if Temporal feels heavy.

**B. AWS Step Functions.** Rejected — couples us to AWS, less ergonomic for Python-heavy agent code, harder to test locally.

**C. Prefect / Dagster.** Rejected — these are data-pipeline orchestrators. They can technically do HITL and long pauses but are not idiomatic. Workflow versioning and signals are weaker.

**D. LangGraph checkpointer + Postgres only.** Rejected for production. Acceptable as a prototype but lacks retries, signal handling, workflow versioning, and operational observability. Building those ourselves would take 6–12 months and we would do it worse than Temporal.

**E. Build our own orchestrator.** Rejected without consideration. Distributed workflow engines are notoriously hard to get right.

## Consequences

**Positive:**

- Probes survive crashes, deploys, infra restarts by construction.
- HITL is first-class — `await_signal` is the right primitive.
- Retries with backoff per-activity, configurable.
- Replay and time-travel debugging via Temporal Web UI is invaluable for postmortems.
- Workflow versioning is built in — in-flight probes are safe across deploys.
- Observability (every activity, every input, every output) is free.
- Mature Python SDK with type safety.

**Negative:**

- Operational footprint: Temporal cluster (frontend, history, matching, worker services) + Postgres + observability stack. Non-trivial to run, especially in on-prem deployments.
- Learning curve for engineers new to durable execution patterns. Determinism rules (no random, no time.now, no I/O outside activities) require discipline.
- Activity payload size limit (2 MB by default) — large evidence bundles must be stored in object storage with references in the payload.
- LangGraph + Temporal integration patterns are less mature than either alone; we will write some glue.

**Neutral:**

- Self-hosted vs cloud is a deferrable decision; we start self-hosted for MVP and can migrate.

## References

- Temporal docs: https://docs.temporal.io
- Temporal Python SDK: https://github.com/temporalio/sdk-python
- [SPEC-004 Probe Workflow](../temporal/SPEC-004-probe-workflow.md)
- [SPEC-005 HITL Gates](../hitl/SPEC-005-hitl-gates.md)
- [ADR-0004 LangGraph](0004-agent-framework-langgraph.md) — how LangGraph nests inside Temporal
