"""Planning agent (Sprint 3 WI3).

Leg-pattern state machine: parse intent -> (resolve asset via HITL if ambiguous) -> load KG
context -> build failure-mode shortlist -> draft plan -> propose to engineer (HITL, batched
with cold-start context questions) -> apply edits / finalize / replan. The node functions map
to the §3.1 LangGraph nodes; ``run_leg`` dispatches on ``state["awaiting"]``.
"""
from __future__ import annotations

from typing import Any, cast

from rca_contracts import (
    AgentLegResult,
    FailureModeCandidate,
    HitlQuestion,
    HitlResponse,
    HitlTurn,
    InvestigationPlan,
    Message,
    PlanStep,
    PlanStepType,
    TokenUsage,
)

from .base import LegContext, det_uuid
from .config import MAX_REPLAN_CYCLES

_RESOLVE_THRESHOLD = 0.85          # §3.1 node 2 — asset confidence gate
_PLANNING_ABORTED = "planning_aborted"
_DEFAULT_LOOKBACK_HOURS = 168


class PlanningAgent:
    async def run_leg(
        self, *, graph_state: dict | None, hitl_response: HitlResponse | None, ctx: LegContext,
    ) -> AgentLegResult:
        state: dict[str, Any] = graph_state or {"agent": "planning", "replan_count": 0}
        messages: list[Message] = []

        if hitl_response is not None:
            awaiting = state.get("awaiting")
            if awaiting == "resolve":
                state = self._apply_resolution(state, hitl_response, messages)
            elif awaiting == "approval":
                outcome = self._apply_approval(state, hitl_response, messages)
                if outcome is not None:
                    return outcome   # finalized or aborted

        if state.get("awaiting") is None and "intent" not in state:
            routed = await self._parse_and_route(state, ctx, messages)
            if routed is not None:
                return routed   # paused on resolve HITL

        return await self._build_and_propose(state, ctx, messages)

    # ---- node: parse_intent + resolve_asset_or_ask -----------------------------
    async def _parse_and_route(
        self, state: dict, ctx: LegContext, messages: list[Message],
    ) -> AgentLegResult | None:
        shortlist = await ctx.toolbox.search_assets(ctx.prompt, ctx.plant_id)
        resp = await ctx.llm.complete(
            "parse_probe_intent", "v1",
            {"prompt": ctx.prompt, "plant_context": f"plant={ctx.plant_id}",
             "asset_shortlist": shortlist, "reference_time": ctx.reference_time.isoformat()},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        intent = resp.structured or {}
        candidates = intent.get("asset_candidates") or shortlist
        confidence = float(intent.get("asset_confidence", candidates[0]["confidence"]
                                      if candidates else 0.0))
        state["intent"] = intent
        state["symptoms"] = intent.get("suspected_symptoms", [])
        state["time_window_hours"] = int(intent.get("time_window_hours", _DEFAULT_LOOKBACK_HOURS))
        state["candidates"] = candidates
        messages.append(Message(role="assistant", content=f"parsed intent; "
                                f"top asset confidence={confidence:.2f}"))

        if confidence < _RESOLVE_THRESHOLD and len(candidates) >= 1:
            return self._emit_resolve_turn(state, ctx, candidates, messages,
                                           [resp.llm_call_id], resp)
        state["resolved_canonical_id"] = candidates[0]["canonical_id"]
        return None

    def _emit_resolve_turn(self, state, ctx, candidates, messages, call_ids, resp):
        # batch the asset choice WITH any other pending clarification (time window) — §3.4
        turn_id = det_uuid(ctx.probe_run_id, "planning", "resolve")
        questions = [
            HitlQuestion(question_id=det_uuid(ctx.probe_run_id, "q", "which_asset"),
                         text="Which asset is this probe about?", question_type="clarification",
                         candidates=candidates, required=True),
            HitlQuestion(question_id=det_uuid(ctx.probe_run_id, "q", "time_window"),
                         text="What lookback window should I use? (default 7 days)",
                         question_type="clarification", required=False),
        ]
        turn = HitlTurn(turn_id=turn_id, questions=questions, context_for_engineer=(
            "The prompt matched more than one asset; please confirm which one and the window."),
            asked_at=ctx.reference_time, agent_name="planning")
        state["awaiting"] = "resolve"
        return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                              new_messages=messages, new_llm_call_ids=call_ids,
                              token_usage_delta=_usage(resp))

    def _apply_resolution(self, state, hitl_response: HitlResponse, messages) -> dict:
        chosen = None
        for ans in hitl_response.answers:
            if ans.chosen_candidate is not None:
                chosen = ans.chosen_candidate.get("canonical_id")
            elif ans.answer and ans.answer.startswith("asset:"):
                chosen = ans.answer
        state["resolved_canonical_id"] = chosen or state["candidates"][0]["canonical_id"]
        state["awaiting"] = None
        messages.append(Message(role="user", content=f"engineer chose "
                                f"{state['resolved_canonical_id']}"))
        return state

    # ---- nodes: load_kg_context, build_shortlist, draft_plan, propose ----------
    async def _build_and_propose(self, state, ctx: LegContext, messages) -> AgentLegResult:
        canonical_id = state["resolved_canonical_id"]
        call_ids = []
        usage = TokenUsage()

        context = await ctx.toolbox.get_asset_context(canonical_id)
        kg_warm = bool(context.get("kg_warm"))
        equipment_class = context.get("iso14224_class")
        applicable = context.get("applicable_failure_modes", [])

        sl_resp = await ctx.llm.complete(
            "build_failure_mode_shortlist", "v1",
            {"symptoms": state.get("symptoms", []), "asset_class": equipment_class,
             "kg_failure_modes": applicable, "prior_events": context.get(
                 "prior_events_on_asset", [])},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        call_ids.append(sl_resp.llm_call_id)
        usage = usage.merged_with(_usage(sl_resp))
        shortlist = self._coerce_shortlist(sl_resp.structured, applicable)

        plan_resp = await ctx.llm.complete(
            "draft_evidence_plan", "v1",
            {"asset": canonical_id, "shortlist": [c.model_dump() for c in shortlist],
             "available_connections": ["historian", "cmms", "document", "operator_log"],
             "kg_context": equipment_class, "reference_time": ctx.reference_time.isoformat()},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        call_ids.append(plan_resp.llm_call_id)
        usage = usage.merged_with(_usage(plan_resp))

        version = int(state.get("plan_version", 0)) + 1
        plan = self._build_plan(ctx, canonical_id, shortlist, plan_resp.structured, version)
        state["plan"] = plan.model_dump(mode="json")
        state["plan_version"] = version
        state["kg_warm"] = kg_warm
        messages.append(Message(role="assistant", content=f"drafted plan v{version} with "
                                f"{len(plan.steps)} steps"))
        return self._propose(state, ctx, plan, kg_warm, messages, call_ids, usage)

    def _propose(self, state, ctx, plan: InvestigationPlan, kg_warm: bool, messages,
                 call_ids, usage) -> AgentLegResult:
        questions: list[HitlQuestion] = []
        if not kg_warm:   # cold-start posture §3.4 — batch context questions up front
            questions.append(HitlQuestion(
                question_id=det_uuid(ctx.probe_run_id, "q", "operation", str(plan.version)),
                text="Is this pump in normal operation right now? Any recent maintenance you "
                     "recall?", question_type="context", required=False))
        questions.append(HitlQuestion(
            question_id=det_uuid(ctx.probe_run_id, "q", "approve_plan", str(plan.version)),
            text="Approve this investigation plan? (edit steps or reject to replan)",
            question_type="approval", required=True))
        turn = HitlTurn(
            turn_id=det_uuid(ctx.probe_run_id, "planning", "approval", str(plan.version)),
            questions=questions, proposed_plan=plan.model_dump(mode="json"),
            context_for_engineer=("Proposed an evidence-gathering plan; assuming a "
                                  f"{plan.steps and state.get('time_window_hours', 168)}h "
                                  "lookback — extend if you've seen issues earlier."),
            asked_at=ctx.reference_time, agent_name="planning")
        state["awaiting"] = "approval"
        return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                              final_output=None, new_messages=messages,
                              new_llm_call_ids=call_ids, token_usage_delta=usage)

    # ---- nodes: apply_plan_edits, finalize_plan, replan ------------------------
    def _apply_approval(self, state, hitl_response: HitlResponse,
                        messages) -> AgentLegResult | None:
        state["awaiting"] = None
        plan = InvestigationPlan.model_validate(state["plan"])
        if hitl_response.plan_edits:
            plan = self._apply_edits(plan, hitl_response)
            state["plan"] = plan.model_dump(mode="json")
            messages.append(Message(role="user", content=f"engineer edited plan "
                                    f"({len(hitl_response.plan_edits)} edits)"))
        if hitl_response.approved:
            plan = plan.model_copy(update={"finalized_at": hitl_response.responded_at,
                                           "engineer_notes": hitl_response.engineer_notes})
            messages.append(Message(role="user", content="engineer approved plan"))
            return AgentLegResult(needs_hitl=False, final_output={"plan": plan.model_dump(
                mode="json")}, graph_state=state, new_messages=messages)
        # rejected
        state["replan_count"] = int(state.get("replan_count", 0)) + 1
        messages.append(Message(role="user", content=f"engineer rejected plan; replan "
                                f"#{state['replan_count']}"))
        if state["replan_count"] > MAX_REPLAN_CYCLES:
            return AgentLegResult(needs_hitl=False, graph_state=state, new_messages=messages,
                                  final_output={"status": _PLANNING_ABORTED})
        return None   # fall through to _build_and_propose (re-propose)

    # ---- builders --------------------------------------------------------------
    def _coerce_shortlist(self, structured: dict | None,
                          applicable: list[dict]) -> list[FailureModeCandidate]:
        cands = (structured or {}).get("candidates") if structured else None
        if cands:
            return [FailureModeCandidate(iso14224_code=c["iso14224_code"], name=c["name"],
                                         rank=c.get("rank", i + 1), confidence=c["confidence"],
                                         reasoning=c.get("reasoning", ""))
                    for i, c in enumerate(cands)]
        # fallback: derive from the applicable ontology modes
        return [FailureModeCandidate(iso14224_code=m["code"], name=m.get("name", m["code"]),
                                     rank=i + 1, confidence=0.5, reasoning="ontology default")
                for i, m in enumerate(applicable[:3])]

    def _build_plan(self, ctx: LegContext, canonical_id: str,
                    shortlist: list[FailureModeCandidate], structured: dict | None,
                    version: int) -> InvestigationPlan:
        steps = self._coerce_steps(ctx, structured, version)
        return InvestigationPlan(
            plan_id=det_uuid(ctx.probe_run_id, "plan"), probe_run_id=ctx.probe_run_id,
            version=version, asset_canonical_id=canonical_id,
            candidate_failure_modes=shortlist, steps=steps)

    def _coerce_steps(self, ctx: LegContext, structured: dict | None,
                      version: int) -> list[PlanStep]:
        raw = (structured or {}).get("steps") if structured else None
        steps: list[PlanStep] = []
        if raw:
            for i, s in enumerate(raw):
                steps.append(PlanStep(
                    step_id=det_uuid(ctx.probe_run_id, "step", str(version), str(i)),
                    step_type=cast(PlanStepType, s["step_type"]),
                    description=s.get("description", s["step_type"]),
                    parameters=s.get("parameters", {}), rationale=s.get("rationale", ""),
                    estimated_cost=s.get("estimated_cost")))
        # Guarantee an opinionated baseline (≥3 steps + a kg_query) even if the LLM was terse.
        present = {s.step_type for s in steps}
        defaults: list[tuple[PlanStepType, str, dict]] = [
            ("tag_history", "Pull tag history for the asset", {"lookback_hours": 168}),
            ("work_orders", "List recent work orders", {}),
            ("documents", "Search asset documents", {"query": "failure"}),
            ("operator_logs", "List operator log entries", {}),
            ("kg_query", "Load KG asset context + applicable failure modes", {})]
        for j, (stype, desc, params) in enumerate(defaults):
            if stype not in present:
                steps.append(PlanStep(
                    step_id=det_uuid(ctx.probe_run_id, "step", str(version), "def", str(j)),
                    step_type=stype, description=desc, parameters=params,
                    rationale="baseline coverage", estimated_cost="fast"))
        return steps

    def _apply_edits(self, plan: InvestigationPlan, hitl: HitlResponse) -> InvestigationPlan:
        steps = list(plan.steps)
        notes = plan.engineer_notes or ""
        for edit in hitl.plan_edits or []:
            if edit.op == "remove_step" and edit.step_id is not None:
                steps = [s for s in steps if s.step_id != edit.step_id]
            elif edit.op == "note" and edit.note:
                notes = (notes + "\n" + edit.note).strip()
        return plan.model_copy(update={"version": plan.version + 1, "steps": steps,
                                       "engineer_notes": notes or hitl.engineer_notes})


def _usage(resp) -> TokenUsage:
    return TokenUsage(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)


def build_graph() -> PlanningAgent:
    """Factory mirroring the future LangGraph ``build_graph()`` seam."""
    return PlanningAgent()


__all__ = ["PlanningAgent", "build_graph"]
