"""RCA agent (WI5 §5.10): fishbone>=3, 5-whys>=3 terminating at root cause, ranked hypotheses
with KG-valid ISO codes, validation_errors, cold-start gap HITL, mid-loop 5-whys HITL, and
approve/reject outcomes. Engine-swap seam is covered in test_probe_workflow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from rca_contracts import (
    AssetSummary,
    CategoryCoverage,
    CoverageReport,
    DocumentEvidence,
    EvidencePackage,
    HierarchyPath,
    HitlAnswer,
    HitlResponse,
    InvestigationPlan,
    ISO14224Context,
    OperatorLogEvidence,
    RcaConclusion,
    TagAnomaly,
    TagEvidence,
    WorkOrderEvidence,
)
from rca_llm import InMemoryResponseCache, LLMClientImpl, default_registry
from rca_llm.client import CompletionResult

from rca_agents.rca_graph import build_graph
from conftest import PROBE_RUN_ID, REF_TIME, leg_ctx

CID = "asset:refinery-gc:unit-101:p-101a"


# A transport that returns fishbone/gaps/rank canned responses and a *sequence* of 5-whys
# steps (root cause on the 3rd), so the iterative loop terminates deterministically.
class _RcaTransport:
    def __init__(self, *, gaps_needs_hitl=False, five_whys_human_at=None):
        self._fw_calls = 0
        self._gaps_needs_hitl = gaps_needs_hitl
        self._human_at = five_whys_human_at

    async def complete(self, *, model, rendered_prompt, temperature, max_tokens, output_schema):
        content = self._route(rendered_prompt)
        return CompletionResult(content=content, model_version=f"{model}-test",
                                input_tokens=10, output_tokens=10)

    def _route(self, prompt: str) -> str:
        if "fishbone" in prompt and "Ishikawa" in prompt:
            return json.dumps({"fishbone": [
                {"category": "Machine", "causes": [{"cause": "worn mechanical seal",
                 "supporting_evidence": [{"section": "work_order", "item_id": "WO-50012402"}]}]},
                {"category": "Method", "causes": [{"cause": "insufficient seal flush flow"}]},
                {"category": "Measurement", "causes": [{"cause": "vibration trending up"}]}]})
        if "whether the engineer should fill" in prompt:
            if self._gaps_needs_hitl:
                return json.dumps({"needs_hitl": True, "questions": [
                    {"text": "When was the seal last replaced?", "question_type": "context"}]})
            return json.dumps({"needs_hitl": False, "questions": []})
        if "Advance the 5 Whys" in prompt:
            self._fw_calls += 1
            n = self._fw_calls
            if self._human_at is not None and n == self._human_at:
                return json.dumps({"why_question": "Was the flush line valved correctly?",
                                   "answer": "", "answer_source": "agent_inference",
                                   "grounded": False, "needs_human_knowledge": True,
                                   "is_root_cause": False})
            root = n >= 3
            return json.dumps({
                "why_question": f"Why #{n}?", "answer": f"cause level {n}",
                "answer_source": "evidence_package", "grounded": True,
                "needs_human_knowledge": False, "is_root_cause": root,
                "supporting_evidence": [{"section": "tag",
                                         "item_id": "P-101A.vibration_radial"}]})
        if "Rank the failure hypotheses" in prompt:
            return json.dumps({
                "primary_hypothesis": {
                    "iso14224_failure_mode": "ELP", "iso14224_mechanism": "failure-mechanism:seal-failure",
                    "confidence": 0.82, "narrative": "mechanical seal leak from dry-running face",
                    "supporting_evidence": [{"section": "work_order", "item_id": "WO-50012402"}]},
                "alternative_hypotheses": [{
                    "iso14224_failure_mode": "VIB", "iso14224_mechanism": "failure-mechanism:imbalance",
                    "confidence": 0.4, "narrative": "vibration from imbalance"}],
                "recommended_actions": [{"action": "Replace mechanical seal",
                    "rationale": "leak confirmed", "priority": "next_shutdown",
                    "target": "mechanical_seal",
                    "preconditions": ["increase_vib_monitoring_frequency_to_daily"]}],
                "open_data_requests": [{"request": "Pull lube oil sample",
                    "rationale": "last sample 90 days old"}]})
        return "{}"


def _llm(transport) -> LLMClientImpl:
    return LLMClientImpl(registry=default_registry(), transport=transport,
                         cache=InMemoryResponseCache())


def _evidence_package() -> EvidencePackage:
    return EvidencePackage(
        evidence_package_id=uuid4(), probe_run_id=PROBE_RUN_ID, canonical_id=CID,
        investigated_failure_modes=["ELP", "VIB"], reference_time=REF_TIME, lookback_hours=168,
        asset=AssetSummary(canonical_id=CID, name="P-101A", iso14224_class="equipment-class:bb1"),
        location=HierarchyPath(plant_id="refinery-gc", unit="UNIT-101"),
        iso14224_context=ISO14224Context(equipment_class="equipment-class:bb1",
            applicable_failure_modes=[{"code": "ELP", "id": "failure-mode:elp", "name": "leak"},
                                      {"code": "VIB", "id": "failure-mode:vib", "name": "vib"}]),
        tag_evidence=TagEvidence(anomalies=[TagAnomaly(tag_name="P-101A.vibration_radial",
                                                       summary="climbing", severity="critical")]),
        work_order_evidence=WorkOrderEvidence(work_orders=[{"work_order_id": "WO-50012402"}]),
        document_evidence=DocumentEvidence(), operator_log_evidence=OperatorLogEvidence(),
        investigation_plan=InvestigationPlan(plan_id=uuid4(), probe_run_id=PROBE_RUN_ID,
                                             version=1, asset_canonical_id=CID),
        coverage=CoverageReport(historian=CategoryCoverage(status="ok"),
                                cmms=CategoryCoverage(status="ok"),
                                documents=CategoryCoverage(status="ok"),
                                operator_log=CategoryCoverage(status="ok")),
        assembled_at=REF_TIME)


def _seed() -> dict:
    return {"agent": "rca", "evidence_package": _evidence_package().model_dump(mode="json")}


def _approve(turn, *, approved=True, actions_approved=True) -> HitlResponse:
    return HitlResponse(turn_id=turn.turn_id, approved=approved, actions_approved=actions_approved,
                        responded_by="eng@deepiq.com",
                        responded_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc))


async def test_produces_conclusion_with_fishbone_fivewhys_and_valid_codes():
    agent = build_graph()
    ctx = leg_ctx(_llm(_RcaTransport()), prompt="P-101A")
    leg = await agent.run_leg(graph_state=_seed(), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True and leg.hitl_turn.proposed_conclusion is not None
    c = RcaConclusion.model_validate(leg.hitl_turn.proposed_conclusion)
    assert len(c.fishbone) >= 3
    assert len(c.five_whys.steps) >= 3
    assert c.five_whys.steps[-1].answer == "cause level 3"   # terminated at root cause
    assert c.primary_hypothesis.iso14224_failure_mode == "ELP"
    assert c.primary_hypothesis.iso14224_mechanism == "failure-mechanism:seal-failure"
    assert c.primary_hypothesis.confidence >= c.alternative_hypotheses[0].confidence
    assert c.recommended_actions[0].target == "mechanical_seal"
    assert c.open_data_requests                # G8
    assert c.validation_errors == []           # everything validates
    # primary cites WO-50012402
    assert any(e.item_id == "WO-50012402" for e in c.primary_hypothesis.supporting_evidence)


async def test_approval_finalizes_conclusion():
    agent = build_graph()
    ctx = leg_ctx(_llm(_RcaTransport()), prompt="P-101A")
    leg = await agent.run_leg(graph_state=_seed(), hitl_response=None, ctx=ctx)
    leg2 = await agent.run_leg(graph_state=leg.graph_state,
                               hitl_response=_approve(leg.hitl_turn), ctx=ctx)
    assert leg2.needs_hitl is False
    c = RcaConclusion.model_validate(leg2.final_output["conclusion"])
    assert c.engineer_approval_status == "approved"
    assert leg2.final_output["actions_approved"] is True


async def test_rejection_twice_persists_conclusion_rejected():
    agent = build_graph()
    ctx = leg_ctx(_llm(_RcaTransport()), prompt="P-101A")
    leg = await agent.run_leg(graph_state=_seed(), hitl_response=None, ctx=ctx)
    leg = await agent.run_leg(graph_state=leg.graph_state,
                              hitl_response=_approve(leg.hitl_turn, approved=False), ctx=ctx)
    assert leg.needs_hitl is True            # regenerated + re-proposed
    leg = await agent.run_leg(graph_state=leg.graph_state,
                              hitl_response=_approve(leg.hitl_turn, approved=False), ctx=ctx)
    assert leg.needs_hitl is False
    assert leg.final_output["status"] == "conclusion_rejected"
    c = RcaConclusion.model_validate(leg.final_output["conclusion"])
    assert c.engineer_approval_status == "rejected"


async def test_cold_start_emits_evidence_gap_hitl_before_five_whys():
    agent = build_graph()
    ctx = leg_ctx(_llm(_RcaTransport(gaps_needs_hitl=True)), prompt="P-101A")
    leg = await agent.run_leg(graph_state=_seed(), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    assert leg.hitl_turn.agent_name == "rca"
    assert "five_whys" not in leg.graph_state    # 5 whys hasn't started yet
    # resume -> proceeds to (eventually) propose a conclusion
    resume = HitlResponse(turn_id=leg.hitl_turn.turn_id, responded_by="eng@deepiq.com",
                          responded_at=REF_TIME,
                          answers=[HitlAnswer(question_id=leg.hitl_turn.questions[0].question_id,
                                              answer="replaced 6 months ago")])
    leg2 = await agent.run_leg(graph_state=leg.graph_state, hitl_response=resume, ctx=ctx)
    assert leg2.hitl_turn.proposed_conclusion is not None


async def test_five_whys_can_emit_mid_loop_hitl():
    agent = build_graph()
    ctx = leg_ctx(_llm(_RcaTransport(five_whys_human_at=2)), prompt="P-101A")
    leg = await agent.run_leg(graph_state=_seed(), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    assert leg.hitl_turn.agent_name == "rca"
    assert "valved correctly" in leg.hitl_turn.questions[0].text
    # resume with the human answer -> loop continues and eventually proposes
    resume = HitlResponse(turn_id=leg.hitl_turn.turn_id, responded_by="eng@deepiq.com",
                          responded_at=REF_TIME,
                          answers=[HitlAnswer(question_id=leg.hitl_turn.questions[0].question_id,
                                              answer="flush line was throttled")])
    leg2 = await agent.run_leg(graph_state=leg.graph_state, hitl_response=resume, ctx=ctx)
    c = RcaConclusion.model_validate(leg2.hitl_turn.proposed_conclusion)
    assert any(s.answer_source == "engineer_hitl" for s in c.five_whys.steps)
