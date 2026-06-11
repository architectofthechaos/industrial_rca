"""Sprint 3 contract shapes: construct, round-trip, and the gap-resolved fields exist."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

import rca_contracts as c


def _dt() -> datetime:
    return datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


def test_token_budget_charge_and_would_exceed():
    b = c.TokenBudget(input_tokens_limit=100, output_tokens_limit=20)
    assert not b.would_exceed(input_tokens=50, output_tokens=10)
    b.charge(input_tokens=50, output_tokens=10)
    assert b.input_used == 50 and b.output_used == 10
    assert b.input_remaining == 50
    assert b.would_exceed(input_tokens=60, output_tokens=0)


def test_token_budget_exceeded_carries_snapshot():
    b = c.TokenBudget()
    err = c.TokenBudgetExceeded("over", budget=b)
    assert err.budget is b


def test_token_usage_merge():
    u = c.TokenUsage(input_tokens=3, output_tokens=1)
    m = u.merged_with(c.TokenUsage(input_tokens=2, output_tokens=4))
    assert (m.input_tokens, m.output_tokens) == (5, 5)


def test_investigation_plan_roundtrips_through_json():
    plan = c.InvestigationPlan(
        plan_id=uuid4(), probe_run_id=uuid4(), version=1,
        asset_canonical_id="asset:refinery-gc:unit-101:p-101a",
        candidate_failure_modes=[
            c.FailureModeCandidate(iso14224_code="ELP", name="external leakage",
                                   rank=1, confidence=0.7, reasoning="seal flush low")],
        steps=[c.PlanStep(step_id=uuid4(), step_type="tag_history",
                          description="pull vibration", parameters={"role": "vibration_radial"},
                          rationale="trend")],
    )
    dumped = plan.model_dump_json()
    back = c.InvestigationPlan.model_validate_json(dumped)
    assert back == plan
    assert back.steps[0].step_type == "tag_history"


def test_plan_step_type_is_constrained():
    with pytest.raises(ValidationError):
        c.PlanStep(step_id=uuid4(), step_type="not_a_type", description="x", rationale="y")


def test_hitl_response_has_responded_by_field_g13():
    r = c.HitlResponse(turn_id=uuid4(), responded_by="eng@x.com", responded_at=_dt(),
                       approved=True)
    assert r.responded_by == "eng@x.com"
    with pytest.raises(ValidationError):   # responded_by is required
        c.HitlResponse(turn_id=uuid4(), responded_at=_dt())


def test_recommended_action_has_target_and_preconditions_g7():
    a = c.RecommendedAction(action="replace seal", rationale="leak", priority="next_shutdown",
                            target="mechanical_seal",
                            preconditions=["increase_vib_monitoring_frequency_to_daily"])
    assert a.target == "mechanical_seal"
    assert a.preconditions == ["increase_vib_monitoring_frequency_to_daily"]


def test_open_data_request_is_its_own_field_g8():
    assert "open_data_requests" in c.RcaConclusion.model_fields


def test_provenance_entry_carries_connection_id_g5():
    pe = c.ProvenanceEntry(section="tag", item_id="P-101A.vibration_radial",
                           connection_id="conn-historian-1", tool_name="tag.get_history",
                           queried_at=_dt(), response_id=uuid4(), record_count=42)
    assert pe.connection_id == "conn-historian-1"


def test_probe_run_status_enum_and_terminality_g18():
    assert c.ProbeRunStatus.COMPLETED.is_terminal
    assert c.ProbeRunStatus.BUDGET_EXCEEDED.is_terminal
    assert c.ProbeRunStatus.PLANNING_ABORTED.is_terminal
    assert c.ProbeRunStatus.CONCLUSION_REJECTED.is_terminal
    assert not c.ProbeRunStatus.GATHERING.is_terminal
    # exact membership — the spec enumerates these in one place
    assert {s.value for s in c.ProbeRunStatus} == {
        "running", "planning", "planning_aborted", "gathering", "analyzing",
        "awaiting_review", "completed", "conclusion_rejected", "budget_exceeded", "failed",
    }


def test_start_probe_request_defaults_g10_g11():
    req = c.StartProbeRequest(prompt="P-101A vibration climbing", requested_by="eng@x.com")
    assert req.plant_id is None and req.reference_time is None


def test_rca_conclusion_roundtrips_and_carries_validation_errors():
    cit = c.EvidenceCitation(section="work_order", item_id="WO-50012402", relevance="seal leak")
    hyp = c.RankedHypothesis(rank=1, iso14224_failure_mode="ELP", iso14224_mechanism="seal-failure",
                             confidence=0.8, narrative="mechanical seal leak",
                             supporting_evidence=[cit])
    chain = c.FiveWhysChain(chain_id=uuid4(), initial_problem="seal leak",
                            steps=[c.FiveWhysStep(rank=1, why_question="why leak?",
                                                  answer="seal face dry", answer_source="evidence_package")],
                            terminal_root_cause="insufficient flush flow", confidence=0.7)
    concl = c.RcaConclusion(
        conclusion_id=uuid4(), probe_run_id=uuid4(), evidence_package_id=uuid4(),
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        primary_hypothesis=hyp,
        fishbone=[c.FishboneCategory(category="Machine",
                                     causes=[c.FishboneCause(cause="worn seal")])],
        five_whys=chain,
        recommended_actions=[c.RecommendedAction(action="replace seal", rationale="leak",
                                                 priority="next_shutdown")],
        open_data_requests=[c.OpenDataRequest(request="lube sample", rationale="90 days old")],
        agent_version="v1", generated_at=_dt(),
    )
    back = c.RcaConclusion.model_validate_json(concl.model_dump_json())
    assert back.primary_hypothesis.iso14224_mechanism == "seal-failure"
    assert back.open_data_requests[0].request == "lube sample"


def test_agent_leg_result_default_token_usage():
    leg = c.AgentLegResult(needs_hitl=False)
    assert leg.token_usage_delta.input_tokens == 0
    assert leg.graph_state == {}


def test_evidence_package_dumps_to_jsonb_safe_payload():
    pkg = c.EvidencePackage(
        evidence_package_id=uuid4(), probe_run_id=uuid4(),
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        investigated_failure_modes=["ELP"], reference_time=_dt(), lookback_hours=168,
        asset=c.AssetSummary(canonical_id="asset:refinery-gc:unit-101:p-101a",
                             name="P-101A", iso14224_class="bb1"),
        location=c.HierarchyPath(plant_id="refinery-gc", unit="UNIT-101"),
        iso14224_context=c.ISO14224Context(equipment_class="bb1"),
        tag_evidence=c.TagEvidence(), work_order_evidence=c.WorkOrderEvidence(),
        document_evidence=c.DocumentEvidence(), operator_log_evidence=c.OperatorLogEvidence(),
        investigation_plan=c.InvestigationPlan(plan_id=uuid4(), probe_run_id=uuid4(), version=1,
                                               asset_canonical_id="asset:refinery-gc:unit-101:p-101a"),
        coverage=c.CoverageReport(
            historian=c.CategoryCoverage(status="ok", record_count=5),
            cmms=c.CategoryCoverage(status="ok"),
            documents=c.CategoryCoverage(status="ok"),
            operator_log=c.CategoryCoverage(status="empty"),
        ),
        assembled_at=_dt(),
    )
    payload = json.loads(pkg.model_dump_json())   # must be JSON-serializable for JSONB
    assert payload["schema_version"] == "v1"
    assert payload["coverage"]["llm_status"] == "ok"
