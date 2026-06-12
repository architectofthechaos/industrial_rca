"""The flywheel — second-probe read through the agent's KG path (Sprint 4 Task 6.1 / WI6, #14).

Stack-gated: SKIPPED unless ``RCA_STACK=1``. Requires the FULL live stack (Temporal :7233 +
probe worker on ``rca-probes`` + the four simulators + Postgres + Neo4j) AND real LLM keys
(``ANTHROPIC_API_KEY``/``VOYAGE_API_KEY``). See ``RUN.md``.

This is the headline "definition of done" demo: a probe #1 on P-101A runs to completion and its
close phase persists a ``HistoricalFailureEvent`` to the KG (via
``Neo4jAssetGraph.persist_failure_event``). Then we read the same asset's context BACK through
the AGENT'S path — an in-process entity MCP host (``build_entity_host`` with a real
``Neo4jAssetGraph``) wrapped in a ``fastmcp.Client`` and an ``McpToolBox`` — and assert the KG
is now warm: ``kg_warm is True`` and ``prior_events_on_asset`` is non-empty. The read goes over
``kg.get_asset_context`` via MCP (not a direct Neo4j query), so it exercises exactly the path
probe #2's gather step uses.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RCA_STACK") != "1",
    reason="requires the live stack (task stack:up + probe:worker + LLM keys); see RUN.md")

P101A = "asset:refinery-gc:unit-101:p-101a"
REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


async def _connect():
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    return await Client.connect("localhost:7233", namespace="default",
                                data_converter=pydantic_data_converter)


def _answer_for(turn: dict) -> "object":
    """Approve approval turns; answer mid-5-Whys human-knowledge questions with a seeded answer
    so the analysis resumes (mirrors test_probe_workflow / test_live_probe_walkthrough)."""
    from rca_contracts import HitlAnswer, HitlResponse

    is_approval = any(q.get("question_type") == "approval" for q in turn.get("questions", []))
    answers = []
    for q in turn.get("questions", []):
        text = "approve" if q.get("question_type") == "approval" else (
            "Seal flush line was partially blocked at the last PM; marginal flush flow dried the "
            "seal faces.")
        answers.append(HitlAnswer(question_id=uuid.UUID(q["question_id"]), answer=text))
    return HitlResponse(
        turn_id=uuid.UUID(turn["turn_id"]), answers=answers,
        approved=True if is_approval else None,
        actions_approved=True if is_approval else None,
        responded_by="eng@deepiq.com", responded_at=REF)


async def _run_probe_to_completion(client, *, prompt: str) -> str:
    """Start a probe, drive every HITL turn to terminal, await the result. Returns probe_run_id."""
    from temporalio.client import WorkflowExecutionStatus

    from rca_agents.api import workflow_id_for
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.workflow import ProbeWorkflow

    rid = str(uuid.uuid4())
    await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt=prompt, plant_id="refinery-gc",
                           requested_by="eng@deepiq.com", probe_run_id=rid),
        id=workflow_id_for(rid), task_queue="rca-probes")
    handle = client.get_workflow_handle(workflow_id_for(rid))

    answered: set[str] = set()
    for _ in range(600):
        desc = await handle.describe()
        if desc.status != WorkflowExecutionStatus.RUNNING:
            break
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if turn and turn["turn_id"] not in answered:
            answered.add(turn["turn_id"])
            await handle.signal(ProbeWorkflow.hitl_response, _answer_for(turn))
        await asyncio.sleep(0.5)
    result = await handle.result()
    assert result.status == "completed", f"probe #1 did not complete: status={result.status!r}"
    return rid


async def test_second_read_reflects_first_probe_event_through_agent_kg_path():
    """#14: after probe #1 persists a failure event to the KG, a read through the agent's KG
    path (kg.get_asset_context over MCP) shows the warm KG — kg_warm True + a prior event."""
    from fastmcp import Client
    from rca_kg.assets import Neo4jAssetGraph

    from rca_agents.host import build_entity_host, router_from_connections
    from rca_agents.mcp_toolbox import McpToolBox

    # 1. Run probe #1 to completion — its close phase persists a HistoricalFailureEvent on P-101A.
    client = await _connect()
    rid1 = await _run_probe_to_completion(client, prompt="RCA on P-101A seal leak")

    # 2. Read the asset context BACK through the agent's path: an in-process entity host over a
    #    real Neo4jAssetGraph + a fastmcp.Client + McpToolBox. This is the same kg.get_asset_context
    #    tool probe #2's gather step calls over MCP (NOT a direct Neo4j query).
    asset_graph = Neo4jAssetGraph()
    host = await build_entity_host(router=await router_from_connections(),
                                   asset_graph=asset_graph)
    async with Client(host) as mcp_client:
        toolbox = McpToolBox(mcp_client, plant_id="refinery-gc")
        ctx = await toolbox.get_asset_context(P101A)

    # 3. The KG is now warm and carries probe #1's event.
    assert ctx["kg_warm"] is True, f"KG should be warm after probe #1; ctx={ctx!r}"
    assert ctx["prior_events_on_asset"], (
        f"expected >= 1 prior failure event on P-101A after probe #1; ctx={ctx!r}")

    # 4. (sanity) the event carries an ISO 14224 failure mode (the conclusion's primary hypothesis).
    first_event = ctx["prior_events_on_asset"][0]
    assert first_event.get("iso14224_failure_mode"), (
        f"prior event missing iso14224_failure_mode: {first_event!r}")

    # 5. (optional) Run probe #2 on the same asset; its gather sees the warm context too. We assert
    #    it completes — the warm read is already proven above through the identical MCP tool path.
    rid2 = await _run_probe_to_completion(client, prompt="RCA on P-101A seal leak (second look)")
    assert rid2 != rid1
