"""Gather agent (WI4 §4.6): full Evidence Package, partial-coverage skip, LLM->3σ anomaly
fallback, and the empty-tag-history -> HITL -> extend-window -> resume path."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from rca_contracts import (
    EvidencePackage,
    FailureModeCandidate,
    HitlResponse,
    InvestigationPlan,
    PlanStep,
)

from rca_agents.gather_graph import build_graph
from rca_agents.toolbox import FakeToolBox
from conftest import PROBE_RUN_ID, leg_ctx, scripted_llm

_ANOMALY_KEY = "Review these per-tag summary"
_ANOMALIES = json.dumps({"anomalies": [
    {"tag_name": "P-101A.vibration_radial", "role": "vibration_radial",
     "summary": "rose to 6.6 mm/s", "severity": "critical"},
    {"tag_name": "P-101A.seal_flush_flow", "summary": "declined 4.5 L/min",
     "severity": "elevated"}]})


def _plan(steps=None) -> InvestigationPlan:
    default_steps = [
        ("tag_history", {"roles": ["vibration_radial"]}),
        ("work_orders", {}),
        ("documents", {"query": "mechanical seal"}),
        ("operator_logs", {}),
        ("kg_query", {}),
    ]
    return InvestigationPlan(
        plan_id=uuid4(), probe_run_id=PROBE_RUN_ID, version=1,
        asset_canonical_id="asset:refinery-gc:unit-101:p-101a",
        candidate_failure_modes=[
            FailureModeCandidate(iso14224_code="ELP", name="External leakage", rank=1,
                                 confidence=0.7, reasoning="seal flush low"),
            FailureModeCandidate(iso14224_code="VIB", name="Vibration", rank=2,
                                 confidence=0.5, reasoning="vib climbing")],
        steps=[PlanStep(step_id=uuid4(), step_type=st, description=st, parameters=p,
                        rationale="r") for st, p in (steps or default_steps)])


def _seed(plan: InvestigationPlan, lookback: int = 168) -> dict:
    return {"agent": "gather", "plan": plan.model_dump(mode="json"), "lookback_hours": lookback}


async def test_happy_path_assembles_full_evidence_package():
    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=FakeToolBox())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False
    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    # non-empty sections for every healthy category
    assert pkg.tag_evidence.tags and pkg.work_order_evidence.work_orders
    assert pkg.document_evidence.documents and pkg.operator_log_evidence.entries
    assert pkg.coverage.historian.status == "ok"
    assert pkg.coverage.cmms.status == "ok"
    assert pkg.tag_evidence.anomaly_method == "llm_v1"
    assert any(a.severity == "critical" for a in pkg.tag_evidence.anomalies)
    assert pkg.document_evidence.score_method == "keyword_overlap"
    # provenance carries connection_id for connector-backed sections (G5)
    assert any(p.connection_id for p in pkg.provenance if p.section == "tag")
    # plan execution notes recorded per step
    assert len(pkg.plan_execution_notes) == len(pkg.investigation_plan.steps)
    assert pkg.investigated_failure_modes == ["ELP", "VIB"]


async def test_anomaly_fallback_to_3sigma_when_llm_unstructured():
    # scripted transport returns non-JSON for the anomaly prompt -> structured None -> fallback
    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: "not json"}), prompt="P-101A", toolbox=FakeToolBox())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    assert pkg.tag_evidence.anomaly_method == "rule:3sigma"
    assert pkg.tag_evidence.anomalies   # 3σ still flags the critical/elevated tags


async def test_partial_coverage_skips_unhealthy_category_and_continues():
    class _NoCmms(FakeToolBox):
        async def work_orders_for_asset(self, canonical_id):
            raise RuntimeError("maximo connection unhealthy")

    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A", toolbox=_NoCmms())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False           # probe continues despite the outage
    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    assert pkg.coverage.cmms.status.startswith("skipped")
    assert pkg.coverage.historian.status == "ok"


async def test_empty_tag_history_triggers_hitl_then_resumes():
    class _EmptyTags(FakeToolBox):
        async def tag_history(self, canonical_id, *, reference_time, lookback_hours):
            if lookback_hours <= 168:                       # empty in the first window
                from rca_agents.toolbox import _prov
                return [], _prov("tag", canonical_id, "tag.get_history",
                                 "conn", 0, reference_time)
            return await super().tag_history(canonical_id, reference_time=reference_time,
                                             lookback_hours=lookback_hours)

    agent = build_graph()
    tb = _EmptyTags()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A", toolbox=tb)
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    assert leg.hitl_turn.questions[0].question_type == "scope"

    resume = HitlResponse(turn_id=leg.hitl_turn.turn_id, approved=True,
                          responded_by="eng@deepiq.com",
                          responded_at=datetime(2026, 3, 30, 13, 0, tzinfo=timezone.utc))
    leg2 = await agent.run_leg(graph_state=leg.graph_state, hitl_response=resume, ctx=ctx)
    assert leg2.needs_hitl is False
    pkg = EvidencePackage.model_validate(leg2.final_output["evidence_package"])
    assert pkg.tag_evidence.tags          # tags present after the window was doubled
    assert pkg.lookback_hours == 336
