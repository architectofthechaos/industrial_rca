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


async def run() -> None:
    """Live entrypoint: build the in-process entity host + client, assemble deps, serve."""
    import os
    from fastmcp import Client
    from temporalio.client import Client as TemporalClient
    from temporalio.contrib.pydantic import pydantic_data_converter

    from rca_kg.assets import Neo4jAssetGraph

    from .config import mcp_host_url, temporal_host, temporal_namespace
    from .deps import build_probe_deps
    from .mcp_toolbox import McpToolBox

    use_pg = os.environ.get("PROBE_USE_POSTGRES", "1") == "1"
    # close-phase persist_conclusion_to_kg writes the KG directly (not over MCP), so the worker
    # holds its own Neo4jAssetGraph independent of the MCP host.
    asset_graph = Neo4jAssetGraph()
    # D8/G10: reach the entity tools over HTTP against the separately-run MCP host
    # (`task probe:host`). The host (rca_agents.host) builds MAR+KG(+asset_graph)+connectors with
    # the registry router. In-process construction stays the hermetic-test path (build_probe_deps
    # with Client(host_obj)); McpToolBox is unchanged — only how the Client is built differs.
    async with Client(mcp_host_url()) as mcp_client:
        deps = build_probe_deps(toolbox=McpToolBox(mcp_client), asset_graph=asset_graph,
                                wo_client=mcp_client, use_postgres=use_pg)
        client = await TemporalClient.connect(temporal_host(), namespace=temporal_namespace(),
                                              data_converter=pydantic_data_converter)
        worker = await make_worker(client, deps)
        await worker.run()


def main() -> None:
    import asyncio
    asyncio.run(run())


if __name__ == "__main__":
    main()


__all__ = ["make_worker", "default_agent_factories", "ProbeWorkflow", "_WORKFLOW_RUNNER",
           "run", "main"]
