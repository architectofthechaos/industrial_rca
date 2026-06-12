"""D4 budget-exhaustion behavior (Sprint 4 WI4, acceptance #7).

Hermetic: reuses the scripted-LLM / in-memory-repo / time-skipping harness from
``test_probe_workflow``. Starts a ProbeWorkflow with a TINY token budget so the FIRST
``llm.complete`` in the planning agent trips ``TokenBudgetExceeded`` (the budget gate runs
PRE-CALL regardless of transport). Asserts the workflow auto-finalizes-partial at terminal
status ``budget_exceeded`` and ``handle.result()`` RETURNS a ProbeResult (does NOT raise a
WorkflowFailureError), and that NO "extend budget?" HITL turn was ever exposed (D4).
"""
from __future__ import annotations

import asyncio

from temporalio.client import WorkflowExecutionStatus

from test_probe_workflow import _deps, _start_env


async def _run_budget(deps, *, input_limit: int, output_limit: int):
    """Start the probe with a tiny budget and drive it (defensively answering any HITL) until
    it leaves RUNNING. Returns (result, seen_budget_hitl)."""
    from rca_agents.config import task_queue
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.worker import make_worker
    from rca_agents.workflow import ProbeWorkflow as PW

    from test_probe_workflow import REF, _auto_response

    env = await _start_env()
    try:
        worker = await make_worker(env.client, deps)
        async with worker:
            handle = await env.client.start_workflow(
                PW.run,
                ProbeWorkflowInput(
                    prompt="P-101A vibration climbing", plant_id="refinery-gc",
                    reference_time=REF, requested_by="eng@deepiq.com",
                    input_tokens_limit=input_limit, output_tokens_limit=output_limit),
                id="probe-budget-1", task_queue=task_queue())

            saw_budget_hitl = False
            answered: set[str] = set()
            for _ in range(4000):
                desc = await handle.describe()
                if desc.status != WorkflowExecutionStatus.RUNNING:
                    break
                turn = await handle.query(PW.pending_hitl_turn)
                if turn and turn["turn_id"] not in answered:
                    answered.add(turn["turn_id"])
                    blob = str(turn).lower()
                    if "budget" in blob or "extend" in blob:
                        saw_budget_hitl = True
                    await handle.signal(PW.hitl_response, _auto_response(turn, approve=True))
                await asyncio.sleep(0.01)
            result = await handle.result()
            return result, saw_budget_hitl
    finally:
        await env.shutdown()


async def test_budget_exhaustion_finalizes_partial():
    """A tiny budget trips the planning agent's first complete() -> the workflow catches
    TokenBudgetExceeded and finalizes the probe at terminal status budget_exceeded, surfacing a
    partial ProbeResult. handle.result() must RETURN (not raise WorkflowFailureError)."""
    deps = _deps()

    # input_tokens_limit=10 / output_tokens_limit=5 is tiny enough that the planning agent's first
    # complete() would_exceed -> raises TokenBudgetExceeded inside the run_agent_leg activity.
    result, saw_budget_hitl = await _run_budget(deps, input_limit=10, output_limit=5)

    # D4 key behavior: result() returns cleanly with the terminal budget_exceeded status.
    assert result.status == "budget_exceeded", (
        f"expected budget_exceeded; got {result.status!r}")

    # The run row was finalized (terminal) by _finalize -> the row is not stuck mid-probe.
    runs = deps.runs.runs
    assert len(runs) == 1
    run = next(iter(runs.values()))
    assert run["status"] == "budget_exceeded", (
        f"run row not finalized budget_exceeded; got {run['status']!r}")
    assert run["completed_at"] is not None       # _finalize ran

    # D4: no "extend budget?" HITL turn was ever exposed.
    assert not saw_budget_hitl, "an 'extend budget?' HITL turn fired, violating D4"
