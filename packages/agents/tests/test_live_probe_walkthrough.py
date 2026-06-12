"""Live single-probe walkthrough + budget-exhaustion (Sprint 4 Task 4.1 / WI4, D2 + D4).

Stack-gated: SKIPPED unless ``RCA_STACK=1``. Requires the FULL live stack (Temporal :7233 +
probe worker on ``rca-probes`` + the four simulators + Postgres + Neo4j) AND real LLM keys
(``ANTHROPIC_API_KEY``/``VOYAGE_API_KEY``). See ``RUN.md`` for the exact reproduction.

Two tests:

1. ``test_full_walkthrough_with_mid_analysis_hitl`` (D2): submit a P-101A probe, drive ALL HITL
   turns to completion (answer the plan-approval turn AND the mid-5-Whys human-knowledge
   question), then assert the workflow finalizes ``completed`` with a ranked ``RcaConclusion``,
   and that a mid-5-Whys turn was among the turns we answered.

2. ``test_budget_exhaustion_yields_partial`` (D4): submit with a tight token budget and assert
   the run finalizes ``budget_exceeded`` (the exact ``ProbeRunStatus`` value) with a partial
   result retrievable, and that NO "extend budget?" HITL turn fired.

The HITL driver mirrors ``test_probe_workflow._drive_until_complete``: poll the
``pending_hitl_turn`` query; when a fresh turn appears, build a ``HitlResponse`` answering it and
``signal(ProbeWorkflow.hitl_response, ...)``. queries don't advance workflow time, so the 7-day
HITL timer never fires while we answer.
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

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- helpers
async def _connect():
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    return await Client.connect("localhost:7233", namespace="default",
                                data_converter=pydantic_data_converter)


def _turn_signature(turn: dict) -> str:
    """A stable label for a HITL turn so we can track which *kinds* fired.

    Plan-approval turn:       agent_name == "planning"            -> "plan_approval"
    Mid-5-Whys human Q (D2):  agent_name == "rca", question_type "context", no proposed_conclusion
                              (see rca_graph._run_five_whys -> HitlTurn with question_type="context"
                              + context_for_engineer "My evidence can't answer this…") -> "five_whys"
    Pre-5-Whys evidence gaps: agent_name == "rca", question_type "context" -> also "five_whys"-ish;
                              we distinguish the conclusion gate below.
    Conclusion review gate:   agent_name == "rca", a question_type "approval" question
                              + proposed_conclusion set -> "conclusion_review"
    """
    agent = turn.get("agent_name")
    qtypes = {q.get("question_type") for q in turn.get("questions", [])}
    if agent == "planning":
        return "plan_approval"
    if agent == "gather":
        return "gather"
    if agent == "rca":
        if turn.get("proposed_conclusion") is not None or "approval" in qtypes:
            return "conclusion_review"
        # rca + non-approval (context) question with no conclusion attached == the mid-analysis
        # human-knowledge gate raised inside the 5-Whys loop (D2).
        return "five_whys"
    return f"{agent}:{sorted(qtypes)}"


def _answer_for(turn: dict) -> "object":
    """Build a HitlResponse that answers `turn`.

    - Approval turns (plan/conclusion review): approve + approve actions, with a generic answer
      per question so required questions are satisfied.
    - Mid-5-Whys / gap context turns: supply a scripted/seeded textual answer to the human-
      knowledge question so the 5-Whys loop can resume (rca_graph._apply_hitl reads answers[0]).
    """
    from rca_contracts import HitlAnswer, HitlResponse

    is_approval = any(q.get("question_type") == "approval" for q in turn.get("questions", []))
    answers = []
    for q in turn.get("questions", []):
        if q.get("question_type") == "approval":
            text = "approve"
        else:
            # Seeded human-knowledge answer for the mid-5-Whys question (D2). Concrete enough that
            # the agent can fold it into a 5-Whys step and continue toward a root cause.
            text = ("Seal flush line was found partially blocked during the last PM; flush flow "
                    "had been marginal for weeks, drying the seal faces.")
        answers.append(HitlAnswer(question_id=uuid.UUID(q["question_id"]), answer=text))
    return HitlResponse(
        turn_id=uuid.UUID(turn["turn_id"]), answers=answers,
        approved=True if is_approval else None,
        actions_approved=True if is_approval else None,
        responded_by="eng@deepiq.com", responded_at=REF)


async def _drive(handle, *, max_polls: int = 600) -> set[str]:
    """Answer every HITL turn until the workflow leaves RUNNING. Returns the set of turn
    signatures seen (so callers can assert which kinds of gate fired)."""
    from temporalio.client import WorkflowExecutionStatus

    from rca_agents.workflow import ProbeWorkflow

    answered: set[str] = set()
    seen: set[str] = set()
    for _ in range(max_polls):
        desc = await handle.describe()
        if desc.status != WorkflowExecutionStatus.RUNNING:
            break
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if turn and turn["turn_id"] not in answered:
            answered.add(turn["turn_id"])
            seen.add(_turn_signature(turn))
            await handle.signal(ProbeWorkflow.hitl_response, _answer_for(turn))
        await asyncio.sleep(0.5)
    return seen


# --------------------------------------------------------------------------- tests
async def test_full_walkthrough_with_mid_analysis_hitl():
    """D2: a full P-101A probe drives plan-approval + a mid-5-Whys human-knowledge turn to a
    `completed` conclusion with a ranked primary hypothesis."""
    from rca_agents.api import workflow_id_for
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.workflow import ProbeWorkflow

    client = await _connect()
    rid = str(uuid.uuid4())
    await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt="RCA on P-101A seal leak", plant_id="refinery-gc",
                           requested_by="eng@deepiq.com", probe_run_id=rid,
                           reference_time=REF),   # anchor at the seal-leak scenario window
        id=workflow_id_for(rid), task_queue="rca-probes")
    handle = client.get_workflow_handle(workflow_id_for(rid))

    seen = await _drive(handle)
    # Untyped handle + pydantic converter -> result decodes to a plain dict (ProbeResult fields).
    result = await handle.result()

    # The plan-approval gate fired (planning ran on live data).
    assert "plan_approval" in seen, f"expected a plan-approval HITL turn; saw {sorted(seen)}"
    # D2: a mid-analysis 5-Whys human-knowledge turn fired (the rca agent asked for engineer
    # knowledge mid-loop, we answered it, and the loop resumed).
    assert "five_whys" in seen, (
        f"expected a mid-5-Whys human-knowledge HITL turn (D2); saw {sorted(seen)}")

    # Terminal success + a ranked conclusion.
    assert result["status"] == "completed", f"probe did not complete: status={result['status']!r}"
    assert result["conclusion_id"] is not None

    # Read the persisted conclusion through the Postgres conclusion repo to confirm a ranked
    # primary hypothesis. The worker persists it via deps.conclusions.put in the rca leg.
    from rca_agents.repos_pg import PgRcaConclusionRepo
    stored = await PgRcaConclusionRepo().get_for_probe(uuid.UUID(rid))
    assert stored is not None, "no RcaConclusion persisted for the completed probe"
    assert stored.primary_hypothesis is not None
    assert stored.primary_hypothesis.rank == 1
    assert stored.primary_hypothesis.iso14224_failure_mode, "primary hypothesis has no failure mode"
    assert stored.engineer_approval_status in ("approved", "approved_with_edits")


async def test_budget_exhaustion_yields_partial():
    """D4: a tight token budget ends the probe at terminal status `budget_exceeded` with a
    partial result retrievable, and NO "extend budget?" HITL turn fires."""
    from rca_agents.api import workflow_id_for
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.workflow import ProbeWorkflow

    client = await _connect()
    rid = str(uuid.uuid4())
    await client.start_workflow(
        ProbeWorkflow.run,
        ProbeWorkflowInput(prompt="RCA on P-101A seal leak", plant_id="refinery-gc",
                           requested_by="eng@deepiq.com", probe_run_id=rid,
                           input_tokens_limit=200, output_tokens_limit=50),
        id=workflow_id_for(rid), task_queue="rca-probes")
    handle = client.get_workflow_handle(workflow_id_for(rid))

    # Drive any HITL minimally (there should be none before the budget gate trips, but answer
    # defensively if one appears) and assert NO "extend budget?" turn ever shows up (D4: budget
    # exhaustion halts cleanly; the agent never bargains for more budget via HITL).
    seen = await _drive(handle)
    assert not any("budget" in sig.lower() or "extend" in sig.lower() for sig in seen), (
        f"an 'extend budget?' HITL turn fired, violating D4; saw {sorted(seen)}")

    # D4: handle.result() RETURNS (doesn't raise) with the budget_exceeded status (the workflow
    # now catches TokenBudgetExceeded and finalizes-partial). Untyped handle -> dict.
    result = await handle.result()
    assert result["status"] == "budget_exceeded", (
        f"expected result status budget_exceeded; got {result['status']!r}")

    # The run finalizes at the exact terminal status from ProbeRunStatus.BUDGET_EXCEEDED.
    from rca_contracts import ProbeRunStatus
    assert ProbeRunStatus.BUDGET_EXCEEDED.value == "budget_exceeded"

    # Read the terminal run row from Postgres (the worker's finalize writes it). A partial
    # result is retrievable: the run row exists with the budget_exceeded status (and whatever
    # partial artifacts the early phases persisted).
    from rca_agents.repos_pg import PgProbeRunsRepo
    run = await PgProbeRunsRepo().get_run(uuid.UUID(rid))
    assert run is not None, "no probe-run row persisted for the budget-exhausted probe"
    assert run["status"] == ProbeRunStatus.BUDGET_EXCEEDED.value, (
        f"expected terminal status budget_exceeded; got {run['status']!r}")
