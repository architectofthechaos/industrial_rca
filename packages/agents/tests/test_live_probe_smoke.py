"""Live first-HITL smoke test (Sprint 4 Task 3.4 / WI3).

Stack-gated: SKIPPED unless ``RCA_STACK=1`` because it requires the FULL live stack
(Temporal :7233 + probe worker on the ``rca-probes`` queue + the four simulators + Postgres +
Neo4j) AND real LLM API keys (``ANTHROPIC_API_KEY``/``VOYAGE_API_KEY``). See ``RUN.md`` for the
exact reproduction.

It submits a P-101A probe through the real Temporal client (NOT a hermetic time-skipping env,
NOT FakeToolBox) and asserts the workflow reaches its first HITL gate — the plan-approval turn —
within ~60s. That alone proves planning ran end-to-end on real MAR/KG/connector data over MCP
with a live LLM: the planning agent resolved the asset, ranked ISO 14224 candidates, and drafted
a plan, then paused for engineer approval.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RCA_STACK") != "1",
    reason="requires the live stack (task stack:up + probe:worker + LLM keys); see RUN.md")


async def test_probe_reaches_first_hitl_with_real_data():
    """Submit a probe via the Temporal client and assert it reaches the plan-approval HITL gate
    using REAL simulator-derived data (not FakeToolBox)."""
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    from rca_agents.api import workflow_id_for
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.workflow import ProbeWorkflow

    client = await Client.connect("localhost:7233", namespace="default",
                                  data_converter=pydantic_data_converter)
    rid = str(uuid.uuid4())
    await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt="RCA on P-101A seal leak", plant_id="refinery-gc",
                           requested_by="pilot", probe_run_id=rid),
        id=workflow_id_for(rid), task_queue="rca-probes")
    handle = client.get_workflow_handle(workflow_id_for(rid))

    # Poll the pending HITL turn (plan approval). queries don't advance workflow time, so the
    # 7-day HITL timer never fires while we poll — once planning pauses, the turn stays pending.
    for _ in range(60):
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if turn:
            # A turn with questions proves planning produced a plan + asked for approval, i.e.
            # the planning agent ran on live MAR/KG/connector data over MCP with a real LLM.
            assert turn["questions"], f"HITL turn fired with no questions: {turn!r}"
            assert turn["agent_name"] == "planning", (
                f"first HITL gate should be the planning plan-approval turn, got {turn!r}")
            return
        await asyncio.sleep(1)
    pytest.fail("probe did not reach a HITL gate within 60s")
