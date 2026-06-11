"""Planning agent (WI3 §3.7 acceptance): cold-start batched HITL, ambiguous-asset resolution,
≥3-step plan, approval -> finalize, edit, and the 2-replan abort limit."""
from __future__ import annotations

from datetime import datetime, timezone

from rca_contracts import HitlAnswer, HitlResponse, InvestigationPlan, PlanEdit

from rca_agents.planning_graph import build_graph
from conftest import (
    PLANNING_RESPONSES_AMBIGUOUS,
    PLANNING_RESPONSES_CLEAR,
    P101A,
    leg_ctx,
    scripted_llm,
)


def _approval(turn, *, approved: bool, edits=None) -> HitlResponse:
    return HitlResponse(turn_id=turn.turn_id, approved=approved, plan_edits=edits,
                        responded_by="eng@deepiq.com",
                        responded_at=datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc),
                        answers=[HitlAnswer(question_id=q.question_id, answer="ok")
                                 for q in turn.questions])


async def test_clear_asset_proposes_plan_with_cold_start_context_question():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_CLEAR),
                  prompt="P-101A discharge pressure dropping and vibration climbing")
    leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)

    assert leg.needs_hitl is True
    assert leg.hitl_turn is not None
    qtypes = {q.question_type for q in leg.hitl_turn.questions}
    assert "context" in qtypes            # cold-start context question (kg_warm False)
    assert "approval" in qtypes           # batched WITH the approval question (§3.4)
    assert leg.hitl_turn.proposed_plan is not None
    plan = InvestigationPlan.model_validate(leg.hitl_turn.proposed_plan)
    assert len(plan.steps) >= 3
    assert all(s.rationale for s in plan.steps)
    assert plan.asset_canonical_id == P101A


async def test_approval_finalizes_plan():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_CLEAR),
                  prompt="P-101A vibration climbing")
    leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)
    leg2 = await agent.run_leg(graph_state=leg.graph_state,
                               hitl_response=_approval(leg.hitl_turn, approved=True), ctx=ctx)
    assert leg2.needs_hitl is False
    assert leg2.final_output is not None
    plan = InvestigationPlan.model_validate(leg2.final_output["plan"])
    assert plan.finalized_at is not None


async def test_ambiguous_asset_first_turn_asks_which_and_batches_clarifications():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_AMBIGUOUS),
                  prompt="the BB1 pump in CDU is noisy")
    leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    texts = [q.text.lower() for q in leg.hitl_turn.questions]
    assert any("which asset" in t for t in texts)        # which pump
    assert len(leg.hitl_turn.questions) >= 2             # batched with the window clarification

    # resume: engineer chooses P-101A -> agent proposes a plan
    resolve = HitlResponse(
        turn_id=leg.hitl_turn.turn_id, responded_by="eng@deepiq.com",
        responded_at=datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc),
        answers=[HitlAnswer(question_id=leg.hitl_turn.questions[0].question_id,
                            answer="that one", chosen_candidate={"canonical_id": P101A})])
    leg2 = await agent.run_leg(graph_state=leg.graph_state, hitl_response=resolve, ctx=ctx)
    assert leg2.needs_hitl is True
    assert leg2.hitl_turn.proposed_plan is not None


async def test_replan_limit_aborts_after_two_rejections():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_CLEAR), prompt="P-101A vibration climbing")
    leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)
    # reject #1 -> re-propose
    leg = await agent.run_leg(graph_state=leg.graph_state,
                              hitl_response=_approval(leg.hitl_turn, approved=False), ctx=ctx)
    assert leg.needs_hitl is True
    # reject #2 -> re-propose
    leg = await agent.run_leg(graph_state=leg.graph_state,
                              hitl_response=_approval(leg.hitl_turn, approved=False), ctx=ctx)
    assert leg.needs_hitl is True
    # reject #3 -> planning_aborted
    leg = await agent.run_leg(graph_state=leg.graph_state,
                              hitl_response=_approval(leg.hitl_turn, approved=False), ctx=ctx)
    assert leg.needs_hitl is False
    assert leg.final_output == {"status": "planning_aborted"}


async def test_plan_edit_is_applied():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_CLEAR), prompt="P-101A vibration climbing")
    leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)
    plan = InvestigationPlan.model_validate(leg.hitl_turn.proposed_plan)
    drop = plan.steps[0].step_id
    resp = HitlResponse(turn_id=leg.hitl_turn.turn_id, approved=True,
                        plan_edits=[PlanEdit(op="remove_step", step_id=drop)],
                        responded_by="eng@deepiq.com",
                        responded_at=datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc))
    leg2 = await agent.run_leg(graph_state=leg.graph_state, hitl_response=resp, ctx=ctx)
    final = InvestigationPlan.model_validate(leg2.final_output["plan"])
    assert drop not in {s.step_id for s in final.steps}


async def test_replay_is_byte_identical_for_same_inputs():
    # two runs of the SAME probe_run_id + prompt produce identical proposed plans (det ids)
    plans = []
    for _ in range(2):
        agent = build_graph()
        ctx = leg_ctx(scripted_llm(PLANNING_RESPONSES_CLEAR), prompt="P-101A vibration climbing")
        leg = await agent.run_leg(graph_state=None, hitl_response=None, ctx=ctx)
        plans.append(leg.hitl_turn.proposed_plan)
    assert plans[0] == plans[1]
