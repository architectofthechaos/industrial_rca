"""RCA agent (Sprint 3 WI5) — fishbone + 5 Whys + ranked hypotheses, three HITL contexts.

Same leg pattern as planning/gather. ``EvidencePackage`` -> ``RcaConclusion`` is the engine
boundary the WI5 engine-swap test pins (any object with ``run_leg`` is a drop-in). HITL can
fire (1) pre-5-whys on evidence gaps, (2) mid-5-whys when an answer needs human knowledge, and
(3) at the terminal conclusion-review gate. Validation (§5.5) populates ``validation_errors``
but never blocks the proposal — the hard block on invalid ISO codes is enforced at KG-persist
time (WI6), which MATCHes the ontology and refuses to write an unknown code (G23).
"""
from __future__ import annotations

from typing import Any

from rca_contracts import (
    AgentLegResult,
    EvidenceCitation,
    EvidencePackage,
    FishboneCategory,
    FishboneCause,
    FiveWhysChain,
    FiveWhysStep,
    HitlQuestion,
    HitlResponse,
    HitlTurn,
    Message,
    OpenDataRequest,
    RankedHypothesis,
    RcaConclusion,
    RecommendedAction,
    TokenUsage,
)

from .base import LegContext, det_uuid
from .config import MAX_CONCLUSION_REGENERATIONS, MAX_FIVE_WHYS_DEPTH

_MIN_FIVE_WHYS = 3
_AGENT_VERSION = "v1"


class RcaAgent:
    async def run_leg(
        self, *, graph_state: dict | None, hitl_response: HitlResponse | None, ctx: LegContext,
    ) -> AgentLegResult:
        state: dict[str, Any] = graph_state or {}
        messages: list[Message] = []
        usage = TokenUsage()
        llm_ids: list = []
        pkg = EvidencePackage.model_validate(state["evidence_package"])

        if hitl_response is not None:
            terminal = await self._apply_hitl(state, hitl_response, ctx, messages, pkg)
            if terminal is not None:
                return terminal

        # build_fishbone (once)
        if "fishbone" not in state:
            u, ids = await self._build_fishbone(state, ctx, pkg)
            usage, llm_ids = usage.merged_with(u), llm_ids + ids
            gaps = await self._detect_gaps(state, ctx, pkg)
            if gaps is not None:
                return _merge(gaps, usage, llm_ids)   # paused on evidence-gap HITL

        # five_whys loop (resumable)
        fw = await self._run_five_whys(state, ctx, pkg)
        if fw is not None:
            return _merge(fw, usage, llm_ids)      # paused on a 5-whys human-knowledge question

        # rank + validate + propose
        return await self._rank_validate_propose(state, ctx, pkg, messages, usage, llm_ids)

    # ---- HITL resume dispatch --------------------------------------------------
    async def _apply_hitl(self, state, hitl: HitlResponse, ctx, messages,
                          pkg) -> AgentLegResult | None:
        awaiting = state.get("awaiting")
        state["awaiting"] = None
        if awaiting == "gaps":
            state["gap_answers"] = [{"q": str(a.question_id), "a": a.answer}
                                    for a in hitl.answers]
            messages.append(Message(role="user", content="engineer filled evidence gaps"))
            return None
        if awaiting == "five_whys":
            steps = state.get("five_whys", [])
            answer = hitl.answers[0].answer if hitl.answers else "unknown"
            steps.append({"rank": len(steps) + 1,
                          "why_question": state.get("pending_why", "why?"), "answer": answer,
                          "answer_source": "engineer_hitl", "supporting_evidence": []})
            state["five_whys"] = steps
            state["pending_why"] = None
            messages.append(Message(role="user", content="engineer answered a 5-whys question"))
            return None
        if awaiting == "conclusion":
            return self._finalize_or_regen(state, hitl, ctx, messages, pkg)
        return None

    # ---- node: build_fishbone --------------------------------------------------
    async def _build_fishbone(self, state, ctx: LegContext, pkg: EvidencePackage):
        resp = await ctx.llm.complete(
            "rca_build_fishbone", "v1",
            {"evidence_package": pkg.model_dump(mode="json"),
             "kg_ontology": pkg.iso14224_context.model_dump(mode="json")},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        state["fishbone"] = (resp.structured or {}).get("fishbone", [])
        return _usage(resp), [resp.llm_call_id]

    # ---- node: detect_evidence_gaps_pre_5whys ----------------------------------
    async def _detect_gaps(self, state, ctx: LegContext,
                           pkg: EvidencePackage) -> AgentLegResult | None:
        if state.get("gaps_checked"):
            return None
        state["gaps_checked"] = True
        kg_warm = bool(pkg.iso14224_context.applicable_failure_modes) and bool(
            pkg.work_order_evidence.work_orders)
        resp = await ctx.llm.complete(
            "rca_detect_evidence_gaps", "v1",
            {"fishbone": state["fishbone"], "evidence_package": pkg.model_dump(mode="json"),
             "kg_warm": kg_warm},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        structured = resp.structured or {}
        questions = []
        for i, q in enumerate(structured.get("questions") or []):
            text = _question_text(q)
            if not text:
                continue   # drop text-less items (the LLM occasionally emits malformed gaps)
            questions.append(HitlQuestion(
                question_id=det_uuid(ctx.probe_run_id, "rca", "gap", str(i)),
                text=text, question_type=_one_of(q.get("question_type"), _QTYPES, "context"),
                required=False))
        if structured.get("needs_hitl") and questions:
            turn = HitlTurn(turn_id=det_uuid(ctx.probe_run_id, "rca", "gaps"),
                            questions=questions,
                            context_for_engineer="A few gaps to fill before the 5 Whys.",
                            asked_at=ctx.reference_time, agent_name="rca")
            state["awaiting"] = "gaps"
            return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                                  token_usage_delta=_usage(resp),
                                  new_llm_call_ids=[resp.llm_call_id])
        return None

    # ---- node: run_five_whys_loop ----------------------------------------------
    async def _run_five_whys(self, state, ctx: LegContext,
                             pkg: EvidencePackage) -> AgentLegResult | None:
        steps: list[dict] = state.get("five_whys", [])
        while len(steps) < MAX_FIVE_WHYS_DEPTH:
            resp = await ctx.llm.complete(
                "rca_run_five_whys_step", "v1",
                {"initial_problem": _initial_problem(pkg), "prior_steps": steps,
                 "evidence_package": pkg.model_dump(mode="json"),
                 "reference_time": ctx.reference_time.isoformat()},
                correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
                budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
            s = resp.structured or {}
            if s.get("needs_human_knowledge") and len(steps) >= 1:
                state["five_whys"] = steps
                state["pending_why"] = s.get("why_question", "why?")
                turn = HitlTurn(
                    turn_id=det_uuid(ctx.probe_run_id, "rca", "fivewhys", str(len(steps))),
                    questions=[HitlQuestion(
                        question_id=det_uuid(ctx.probe_run_id, "rca", "why", str(len(steps))),
                        text=s.get("why_question", "why?"), question_type="context",
                        required=True)],
                    context_for_engineer="My evidence can't answer this — your input?",
                    asked_at=ctx.reference_time, agent_name="rca")
                state["awaiting"] = "five_whys"
                return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                                      token_usage_delta=_usage(resp),
                                      new_llm_call_ids=[resp.llm_call_id])
            steps.append({
                "rank": len(steps) + 1, "why_question": s.get("why_question", "why?"),
                "answer": s.get("answer", "unknown"),
                "answer_source": _one_of(s.get("answer_source"), _ANSWER_SOURCES,
                                         "agent_inference"),
                "supporting_evidence": s.get("supporting_evidence", [])})
            if s.get("is_root_cause") and len(steps) >= _MIN_FIVE_WHYS:
                break
        state["five_whys"] = steps
        return None

    # ---- nodes: rank_hypotheses, validate_conclusion, propose ------------------
    async def _rank_validate_propose(self, state, ctx: LegContext, pkg: EvidencePackage,
                                     messages, usage, llm_ids) -> AgentLegResult:
        valid_codes = sorted({m["code"] for m in pkg.iso14224_context.applicable_failure_modes})
        valid_mechanisms = sorted({mech["id"]
                                   for m in pkg.iso14224_context.applicable_failure_modes
                                   for mech in m.get("mechanisms", []) if mech.get("id")})
        resp = await ctx.llm.complete(
            "rca_rank_hypotheses", "v1",
            {"evidence_package": pkg.model_dump(mode="json"), "fishbone": state["fishbone"],
             "five_whys": state["five_whys"], "kg_valid_codes": valid_codes,
             "kg_valid_mechanisms": valid_mechanisms},
            correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
            budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
        usage = usage.merged_with(_usage(resp))
        llm_ids = llm_ids + [resp.llm_call_id]
        conclusion = self._build_conclusion(state, ctx, pkg, resp.structured or {}, valid_mechanisms)
        conclusion = self._validate(conclusion, pkg, valid_codes)
        state["conclusion"] = conclusion.model_dump(mode="json")
        messages.append(Message(role="assistant", content="proposing RCA conclusion"))

        turn = HitlTurn(
            turn_id=det_uuid(ctx.probe_run_id, "rca", "conclusion",
                             str(state.get("regen_count", 0))),
            questions=[
                HitlQuestion(question_id=det_uuid(ctx.probe_run_id, "rca", "approve_conclusion"),
                             text="Approve this RCA conclusion?", question_type="approval"),
                HitlQuestion(question_id=det_uuid(ctx.probe_run_id, "rca", "approve_actions"),
                             text="Approve the recommended actions for a follow-up WO?",
                             question_type="approval", required=False)],
            proposed_conclusion=conclusion.model_dump(mode="json"),
            context_for_engineer="RCA complete; review the conclusion and recommended actions.",
            asked_at=ctx.reference_time, agent_name="rca")
        state["awaiting"] = "conclusion"
        return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                              new_messages=messages, token_usage_delta=usage,
                              new_llm_call_ids=llm_ids)

    def _finalize_or_regen(self, state, hitl: HitlResponse, ctx, messages,
                           pkg) -> AgentLegResult | None:
        conclusion = RcaConclusion.model_validate(state["conclusion"])
        if hitl.approved:
            edits = hitl.conclusion_edits or []
            status = "approved_with_edits" if edits else "approved"
            conclusion = conclusion.model_copy(update={
                "engineer_approval_status": status, "engineer_notes": hitl.engineer_notes,
                "finalized_at": hitl.responded_at,
                "engineer_edits": [self._edit(e, hitl) for e in edits]})
            messages.append(Message(role="user", content=f"engineer {status} the conclusion"))
            return AgentLegResult(needs_hitl=False, graph_state=state, new_messages=messages,
                                  final_output={"conclusion": conclusion.model_dump(mode="json"),
                                                "actions_approved": bool(
                                                    hitl.actions_approved
                                                    if hitl.actions_approved is not None
                                                    else True)})
        # rejected
        state["regen_count"] = int(state.get("regen_count", 0)) + 1
        messages.append(Message(role="user", content="engineer rejected the conclusion"))
        if state["regen_count"] > MAX_CONCLUSION_REGENERATIONS:
            rejected = conclusion.model_copy(update={
                "engineer_approval_status": "rejected", "finalized_at": hitl.responded_at,
                "engineer_notes": hitl.engineer_notes})
            return AgentLegResult(
                needs_hitl=False, graph_state=state, new_messages=messages,
                final_output={"conclusion": rejected.model_dump(mode="json"),
                              "status": "conclusion_rejected"})
        # regenerate: drop the conclusion + rerank
        state.pop("conclusion", None)
        return None

    # ---- builders / validation -------------------------------------------------
    def _build_conclusion(self, state, ctx: LegContext, pkg: EvidencePackage,
                          ranked: dict,
                          valid_mechanisms: list[str] | None = None) -> RcaConclusion:
        regen = int(state.get("regen_count", 0))
        vocab = frozenset(valid_mechanisms) if valid_mechanisms else None  # hash once, not per-hyp
        primary = self._hyp(ranked.get("primary_hypothesis", {}), rank=1, valid_mechanisms=vocab)
        alts = [self._hyp(h, rank=i + 2, valid_mechanisms=vocab)
                for i, h in enumerate(ranked.get("alternative_hypotheses", []))]
        fishbone = [FishboneCategory(
            category=_one_of(c.get("category") or c.get("name"), _FISHBONE_CATS, "Method"),
            causes=[self._cause(x) for x in c.get("causes", [])])
            for c in state["fishbone"]]
        five_whys = FiveWhysChain(
            chain_id=det_uuid(ctx.probe_run_id, "fivewhys"),
            initial_problem=_initial_problem(pkg),
            steps=[self._fw_step(s) for s in state["five_whys"]],
            terminal_root_cause=(state["five_whys"][-1]["answer"] if state["five_whys"]
                                 else "undetermined"),
            confidence=primary.confidence)
        actions = [RecommendedAction(
            action=_act, rationale=a.get("rationale", ""),
            priority=_one_of(a.get("priority"), _PRIORITIES, "monitor"),
            estimated_effort=a.get("estimated_effort"), target=a.get("target"),
            preconditions=a.get("preconditions", []))
            for a in ranked.get("recommended_actions", [])
            if (_act := (a.get("action") or a.get("recommendation") or a.get("description")))]
        odrs = [OpenDataRequest(request=_req, rationale=o.get("rationale", ""),
                                target=o.get("target"))
                for o in ranked.get("open_data_requests", [])
                if (_req := (o.get("request") or o.get("question") or o.get("description")))]
        return RcaConclusion(
            conclusion_id=det_uuid(ctx.probe_run_id, "conclusion", str(regen)),
            probe_run_id=ctx.probe_run_id, evidence_package_id=pkg.evidence_package_id,
            canonical_id=pkg.canonical_id, primary_hypothesis=primary,
            alternative_hypotheses=alts, fishbone=fishbone, five_whys=five_whys,
            recommended_actions=actions, open_data_requests=odrs,
            agent_version=_AGENT_VERSION, generated_at=ctx.reference_time)

    def _validate(self, c: RcaConclusion, pkg: EvidencePackage,
                  valid_codes: list[str]) -> RcaConclusion:
        errors: list[str] = []
        hyps = [c.primary_hypothesis, *c.alternative_hypotheses]
        valid = set(valid_codes)
        for h in hyps:
            if valid and h.iso14224_failure_mode not in valid:
                errors.append(f"failure mode {h.iso14224_failure_mode} not in KG ontology")
        if c.alternative_hypotheses and any(
                a.confidence > c.primary_hypothesis.confidence for a in c.alternative_hypotheses):
            errors.append("a primary hypothesis confidence is below an alternative's")
        if len(c.five_whys.steps) < _MIN_FIVE_WHYS:
            errors.append(f"five_whys has < {_MIN_FIVE_WHYS} steps")
        if len(c.fishbone) < 3:
            errors.append("fishbone has < 3 populated categories")
        if not c.recommended_actions:
            errors.append("recommended_actions is empty")
        return c.model_copy(update={"validation_errors": errors})

    @staticmethod
    def _hyp(h: dict, *, rank: int,
             valid_mechanisms: frozenset[str] | None = None) -> RankedHypothesis:
        mech = h.get("iso14224_mechanism", "failure-mechanism:other")
        if valid_mechanisms and mech not in valid_mechanisms:
            mech = "failure-mechanism:other"
        return RankedHypothesis(
            rank=rank, iso14224_failure_mode=h.get("iso14224_failure_mode", "UNK"),
            iso14224_mechanism=mech,
            iso14224_cause=h.get("iso14224_cause"), confidence=float(h.get("confidence", 0.5)),
            narrative=h.get("narrative", ""),
            supporting_evidence=[_cite(e) for e in h.get("supporting_evidence", [])])

    @staticmethod
    def _cause(x: dict) -> FishboneCause:
        return FishboneCause(
            cause=x.get("cause") or x.get("name") or x.get("description") or "unspecified",
            sub_causes=x.get("sub_causes", []),
            supporting_evidence=[_cite(e) for e in x.get("supporting_evidence", [])])

    @staticmethod
    def _fw_step(s: dict) -> FiveWhysStep:
        return FiveWhysStep(rank=s["rank"], why_question=s["why_question"], answer=s["answer"],
                            answer_source=s.get("answer_source", "agent_inference"),
                            supporting_evidence=[_cite(e) for e in s.get(
                                "supporting_evidence", [])])

    @staticmethod
    def _edit(e, hitl: HitlResponse):
        from rca_contracts import EngineerEdit
        return EngineerEdit(field_path=e.field_path, after=e.after,
                            edited_at=hitl.responded_at, engineer_notes=e.note)


def _merge(leg: AgentLegResult, usage: TokenUsage, llm_ids: list) -> AgentLegResult:
    """Fold accumulated usage/audit ids into a paused leg (AgentLegResult is frozen)."""
    return leg.model_copy(update={
        "token_usage_delta": usage.merged_with(leg.token_usage_delta),
        "new_llm_call_ids": llm_ids + list(leg.new_llm_call_ids)})


def _cite(e: dict) -> EvidenceCitation:
    return EvidenceCitation(section=e.get("section", "tag"), item_id=e.get("item_id", ""),
                            relevance=e.get("relevance"))


def _question_text(q: dict) -> str | None:
    """The human-readable text of an LLM gap question, tolerant of key variants.

    The live LLM does not always honor the prompt's declared ``text`` key (Anthropic JSON
    schema is best-effort) — it has emitted ``question``/``gap``/``description``. Returns the
    first non-empty variant, else None so the caller can drop a text-less item (G25)."""
    for key in ("text", "question", "gap", "description"):
        val = q.get(key)
        if val:
            return str(val)
    return None


# Literal/enum vocabularies the LLM populates (mirror the rca_contracts Literals). The live LLM
# emits out-of-vocab values (e.g. question_type="maintenance_history", category="machine"), which
# crash Pydantic Literal validation — ``_one_of`` canonicalizes case-insensitively or defaults (G25).
_QTYPES = ("clarification", "context", "scope", "approval")
_ANSWER_SOURCES = ("evidence_package", "kg", "engineer_hitl", "agent_inference")
_PRIORITIES = ("immediate", "next_shutdown", "monitor")
_FISHBONE_CATS = ("Manpower", "Method", "Machine", "Material", "Measurement", "Environment")


def _one_of(value: object, allowed: tuple[str, ...], default: str) -> Any:
    # -> Any: the result is a runtime-validated member of `allowed`, assigned to the various
    # Literal enum fields (question_type/category/priority/answer_source) which mypy can't narrow
    # a str to. Membership is guaranteed here, so Any is the honest, cast-free annotation.
    if isinstance(value, str):
        for a in allowed:
            if value.strip().lower() == a.lower():
                return a
    return default


def _initial_problem(pkg: EvidencePackage) -> str:
    anomalies = ", ".join(a.summary for a in pkg.tag_evidence.anomalies[:2])
    return f"{pkg.asset.name}: {anomalies or 'developing failure'}"


def _usage(resp) -> TokenUsage:
    return TokenUsage(input_tokens=resp.input_tokens, output_tokens=resp.output_tokens)


def build_graph() -> RcaAgent:
    return RcaAgent()


__all__ = ["RcaAgent", "build_graph"]
