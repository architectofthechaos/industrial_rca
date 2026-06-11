"""End-to-end ProbeWorkflow (Sprint 3 cross-cutting acceptance).

Hermetic: time-skipping Temporal test env + in-memory repos + seeded InMemoryAssetGraph +
FakeToolBox + a scripted LLM (no SDK, no network). Drives the two HITL gates (plan approval,
conclusion review) via the signal bridge, asserts the probe completes, the failure event is
persisted to the KG (flywheel), and the follow-up WO is created. Also covers the WI5 engine-swap
seam and the conclusion-rejected path.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from rca_contracts import HitlAnswer, HitlResponse
from rca_llm import InMemoryResponseCache, LLMClientImpl, default_registry
from rca_llm.client import CompletionResult
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from rca_agents import gather_graph, planning_graph, rca_graph
from rca_agents.activities import ProbeActivityDeps
from rca_kg.assets import InMemoryAssetGraph

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
CID = "asset:refinery-gc:unit-101:p-101a"
_BB1 = "equipment-class:bb1"
_ELP = "failure-mode:elp"
_SEAL = "failure-mechanism:seal-failure"


def seeded_asset_graph() -> InMemoryAssetGraph:
    """InMemoryAssetGraph carrying the minimal ontology persist_failure_event validates against
    (ELP failure mode + seal-failure mechanism + the Unit P-101A hangs under)."""
    nodes = {
        ("EquipmentClass", _BB1): {"id": _BB1, "code": "BB1"},
        ("FailureMode", _ELP): {"id": _ELP, "code": "ELP", "name": "External leakage"},
        ("FailureMechanism", _SEAL): {"id": _SEAL, "name": "Seal failure"},
        ("Unit", "unit:refinery-gc:unit-101"): {"id": "unit:refinery-gc:unit-101",
                                                "name": "UNIT-101", "plant_id": "refinery-gc"},
    }
    edges = [(_BB1, "CAN_EXHIBIT", _ELP)]
    return InMemoryAssetGraph(nodes=nodes, edges=edges)


# --------------------------------------------------------------------- combined scripted LLM
class _ProbeTransport:
    """Routes every probe prompt; the 5-whys gets a deterministic 3-step sequence."""

    def __init__(self) -> None:
        self._fw = 0

    async def complete(self, *, model, rendered_prompt, temperature, max_tokens, output_schema):
        return CompletionResult(content=self._route(rendered_prompt),
                                model_version=f"{model}-test", input_tokens=20, output_tokens=20)

    def _route(self, p: str) -> str:
        if "planning agent for an industrial" in p:
            return json.dumps({"asset_candidates": [{"canonical_id": CID, "confidence": 0.95}],
                               "suspected_symptoms": ["vibration climbing"],
                               "time_window_hours": 168, "asset_confidence": 0.95})
        if "Rank the candidate ISO 14224" in p:
            return json.dumps({"candidates": [
                {"iso14224_code": "ELP", "name": "External leakage", "rank": 1,
                 "confidence": 0.7, "reasoning": "seal flush low"},
                {"iso14224_code": "VIB", "name": "Vibration", "rank": 2, "confidence": 0.5,
                 "reasoning": "vib climbing"}]})
        if "Draft an opinionated" in p:
            return json.dumps({"steps": [
                {"step_type": "tag_history", "description": "trends",
                 "parameters": {"lookback_hours": 168}, "rationale": "trend"},
                {"step_type": "work_orders", "description": "WOs", "parameters": {},
                 "rationale": "history"},
                {"step_type": "documents", "description": "docs",
                 "parameters": {"query": "mechanical seal"}, "rationale": "context"}]})
        if "Review these per-tag summary" in p:
            return json.dumps({"anomalies": [
                {"tag_name": "P-101A.vibration_radial", "summary": "climbing",
                 "severity": "critical"}]})
        if "Ishikawa" in p:
            return json.dumps({"fishbone": [
                {"category": "Machine", "causes": [{"cause": "worn seal", "supporting_evidence": [
                    {"section": "work_order", "item_id": "WO-50012402"}]}]},
                {"category": "Method", "causes": [{"cause": "low flush flow"}]},
                {"category": "Measurement", "causes": [{"cause": "vibration up"}]}]})
        if "whether the engineer should fill" in p:
            return json.dumps({"needs_hitl": False, "questions": []})
        if "Advance the 5 Whys" in p:
            self._fw += 1
            return json.dumps({"why_question": f"why #{self._fw}", "answer": f"cause {self._fw}",
                               "answer_source": "evidence_package", "grounded": True,
                               "needs_human_knowledge": False, "is_root_cause": self._fw >= 3,
                               "supporting_evidence": [{"section": "tag",
                                                        "item_id": "P-101A.vibration_radial"}]})
        if "Rank the failure hypotheses" in p:
            return json.dumps({
                "primary_hypothesis": {"iso14224_failure_mode": "ELP",
                    "iso14224_mechanism": "failure-mechanism:seal-failure", "confidence": 0.82,
                    "narrative": "mechanical seal leak",
                    "supporting_evidence": [{"section": "work_order", "item_id": "WO-50012402"}]},
                "alternative_hypotheses": [{"iso14224_failure_mode": "VIB",
                    "iso14224_mechanism": "failure-mechanism:imbalance", "confidence": 0.4,
                    "narrative": "imbalance"}],
                "recommended_actions": [{"action": "Replace mechanical seal",
                    "rationale": "leak", "priority": "next_shutdown", "target": "mechanical_seal"}],
                "open_data_requests": [{"request": "lube sample", "rationale": "90d old"}]})
        return "{}"


def _llm() -> LLMClientImpl:
    return LLMClientImpl(registry=default_registry(), transport=_ProbeTransport(),
                         cache=InMemoryResponseCache())


def _deps(agent_factories=None, asset_graph=None):
    from rca_agents.repos import (
        InMemoryEvidencePackageRepo,
        InMemoryProbeMemoryRepo,
        InMemoryProbeRunsRepo,
        InMemoryRcaConclusionRepo,
    )
    from rca_agents.toolbox import FakeToolBox
    from rca_agents.wo import FakeWorkOrderCreator
    ag = asset_graph if asset_graph is not None else seeded_asset_graph()
    return ProbeActivityDeps(
        llm=_llm(), toolbox=FakeToolBox(), asset_graph=ag, wo_creator=FakeWorkOrderCreator(),
        runs=InMemoryProbeRunsRepo(), memory=InMemoryProbeMemoryRepo(),
        evidence=InMemoryEvidencePackageRepo(), conclusions=InMemoryRcaConclusionRepo(),
        agent_factories=agent_factories or {
            "planning": planning_graph.build_graph, "gather": gather_graph.build_graph,
            "rca": rca_graph.build_graph})


# --------------------------------------------------------------------- HITL driver
def _auto_response(turn: dict, *, approve: bool = True) -> HitlResponse:
    return HitlResponse(
        turn_id=turn["turn_id"], approved=approve, actions_approved=True,
        responded_by="eng@deepiq.com", responded_at=REF,
        answers=[HitlAnswer(question_id=q["question_id"], answer="ok")
                 for q in turn["questions"]])


async def _drive_until_complete(handle, *, conclusion_approve: bool):
    """Respond to every HITL turn (approve planning/gather, approve-or-reject RCA conclusion)
    until the workflow finishes. Polls query+describe; queries/describe don't skip workflow
    time, so the 7-day HITL timer never fires while we're answering."""
    from temporalio.client import WorkflowExecutionStatus

    from rca_agents.workflow import ProbeWorkflow
    answered: set[str] = set()
    for _ in range(4000):
        desc = await handle.describe()
        if desc.status != WorkflowExecutionStatus.RUNNING:
            break
        turn = await handle.query(ProbeWorkflow.pending_hitl_turn)
        if turn and turn["turn_id"] not in answered:
            answered.add(turn["turn_id"])
            approve = conclusion_approve if turn["agent_name"] == "rca" else True
            await handle.signal(ProbeWorkflow.hitl_response,
                                _auto_response(turn, approve=approve))
        await asyncio.sleep(0.01)
    return await handle.result()


async def _start_env() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"time-skipping test server unavailable: {type(exc).__name__}: {exc}")


async def _run(deps, *, approve_conclusion: bool = True):
    from rca_agents.config import task_queue
    from rca_agents.models import ProbeWorkflowInput
    from rca_agents.worker import make_worker
    from rca_agents.workflow import ProbeWorkflow
    env = await _start_env()
    try:
        worker = await make_worker(env.client, deps)
        async with worker:
            handle = await env.client.start_workflow(
                ProbeWorkflow.run,
                ProbeWorkflowInput(prompt="P-101A vibration climbing", plant_id="refinery-gc",
                                   reference_time=REF, requested_by="eng@deepiq.com"),
                id="probe-test-1", task_queue=task_queue())
            return await _drive_until_complete(handle, conclusion_approve=approve_conclusion)
    finally:
        await env.shutdown()


# --------------------------------------------------------------------- tests
async def test_end_to_end_probe_completes_persists_event_and_creates_wo():
    deps = _deps()
    result = await _run(deps)
    assert result.status == "completed"
    assert result.canonical_id == CID
    assert result.failure_event_id is not None
    assert result.followup_wo_id and result.followup_wo_id.startswith("WO-RCA-")
    assert result.wo_creation_status == "created"

    # KG flywheel: the failure event is now persisted + retrievable (§6.7)
    ctx = await deps.asset_graph.get_asset_context(canonical_id=CID)
    assert ctx.kg_warm is True
    assert len(ctx.prior_events_on_asset) == 1
    assert ctx.prior_events_on_asset[0].iso14224_failure_mode == "ELP"

    # the conclusion + evidence package were persisted
    conclusion = await deps.conclusions.get_for_probe(_only_probe(deps))
    assert conclusion is not None and conclusion.engineer_approval_status == "approved"
    ep = await deps.evidence.get_for_probe(_only_probe(deps))
    assert ep is not None and ep.tag_evidence.anomalies


async def test_rejected_conclusion_finalizes_conclusion_rejected_and_skips_close():
    deps = _deps()
    result = await _run(deps, approve_conclusion=False)
    assert result.status == "conclusion_rejected"
    assert result.failure_event_id is None    # WI6 skipped entirely (§6.1)


async def test_engine_swap_fake_rca_still_completes_workflow():
    # WI5 §5.8: replace rca_graph.build_graph with a fake that runs to completion in one shot.
    class _FakeRca:
        async def run_leg(self, *, graph_state, hitl_response, ctx):
            from rca_contracts import (AgentLegResult, FiveWhysChain, FiveWhysStep,
                                       FishboneCategory, FishboneCause, RankedHypothesis,
                                       RcaConclusion, RecommendedAction)
            from rca_agents.base import det_uuid
            from rca_contracts import EvidencePackage
            pkg = EvidencePackage.model_validate(graph_state["evidence_package"])
            if hitl_response is not None:   # second leg: engineer approved -> finalize
                c = RcaConclusion.model_validate(graph_state["conclusion"]).model_copy(
                    update={"engineer_approval_status": "approved",
                            "finalized_at": hitl_response.responded_at})
                return AgentLegResult(needs_hitl=False, graph_state=graph_state,
                                      final_output={"conclusion": c.model_dump(mode="json"),
                                                    "actions_approved": True})
            c = RcaConclusion(
                conclusion_id=det_uuid(ctx.probe_run_id, "fake"), probe_run_id=ctx.probe_run_id,
                evidence_package_id=pkg.evidence_package_id, canonical_id=pkg.canonical_id,
                primary_hypothesis=RankedHypothesis(rank=1, iso14224_failure_mode="ELP",
                    iso14224_mechanism="failure-mechanism:seal-failure", confidence=0.9,
                    narrative="fake engine"),
                fishbone=[FishboneCategory(category="Machine",
                                           causes=[FishboneCause(cause="seal")])],
                five_whys=FiveWhysChain(chain_id=det_uuid(ctx.probe_run_id, "fw"),
                    initial_problem="x", terminal_root_cause="dry seal", confidence=0.9,
                    steps=[FiveWhysStep(rank=i, why_question="w", answer="a",
                                        answer_source="agent_inference") for i in (1, 2, 3)]),
                recommended_actions=[RecommendedAction(action="replace seal", rationale="leak",
                                                       priority="next_shutdown")],
                agent_version="fake", generated_at=ctx.reference_time)
            from rca_contracts import HitlQuestion, HitlTurn
            graph_state["conclusion"] = c.model_dump(mode="json")
            turn = HitlTurn(turn_id=det_uuid(ctx.probe_run_id, "fake", "review"),
                            questions=[HitlQuestion(
                                question_id=det_uuid(ctx.probe_run_id, "fq"),
                                text="approve?", question_type="approval")],
                            proposed_conclusion=c.model_dump(mode="json"),
                            context_for_engineer="fake", asked_at=ctx.reference_time,
                            agent_name="rca")
            return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=graph_state)

    deps = _deps(agent_factories={
        "planning": planning_graph.build_graph, "gather": gather_graph.build_graph,
        "rca": lambda: _FakeRca()})
    result = await _run(deps)
    assert result.status == "completed"     # workflow completes with the swapped engine
    assert result.failure_event_id is not None


def _only_probe(deps):
    return next(iter(deps.runs.runs))   # the single probe_run_id (a UUID key)
