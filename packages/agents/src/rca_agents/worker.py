"""Probe Temporal worker (Sprint 3) — serves the ``rca-probes`` task queue (G12).

Mirrors the onboarding worker: pydantic data converter, a sandboxed workflow runner with the
fastmcp/beartype/rca_* passthrough, and deps injected via ``set_activity_deps`` at startup.
``default_agent_factories`` wires the three real agents; tests swap any of them (the WI5
engine-swap seam).
"""
from __future__ import annotations

from collections.abc import Callable

from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from .activities import ALL_ACTIVITIES, ProbeActivityDeps, set_activity_deps
from .base import Agent
from .config import task_queue
from . import gather_graph, planning_graph, rca_graph
from .workflow import ProbeWorkflow

_WORKFLOW_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules(
        "beartype", "fastmcp", "jsonschema", "yaml", "rca_contracts", "rca_llm", "rca_kg",
        "rca_mar", "rca_connector_sdk", "rca_agents"))


def default_agent_factories() -> dict[str, Callable[[], Agent]]:
    return {"planning": planning_graph.build_graph, "gather": gather_graph.build_graph,
            "rca": rca_graph.build_graph}


async def make_worker(client, deps: ProbeActivityDeps):
    """Build (don't run) a worker over an existing Temporal client + injected deps."""
    set_activity_deps(deps)
    return Worker(client, task_queue=task_queue(), workflows=[ProbeWorkflow],
                  activities=ALL_ACTIVITIES, workflow_runner=_WORKFLOW_RUNNER)


__all__ = ["make_worker", "default_agent_factories", "ProbeWorkflow", "_WORKFLOW_RUNNER"]
