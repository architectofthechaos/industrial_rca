"""D14 (Sprint 6 WI2) — failure_modes_for_class returns modes WITH mechanisms.

The FakeToolBox fixture carries real CAUSED_BY mechanism ids from the KG seed
(iso14224_bb1.cypher). McpToolBox delegates to kg.list_failure_modes_for_class.

Also covers that gather enriches the EvidencePackage's iso14224_context with the
mechanism-carrying modes from failure_modes_for_class (not the bare context modes).

Sprint 6 WI2 D14 payoff: the rank prompt receives kg_valid_mechanisms and the
_hyp coercer maps out-of-vocab mechanism ids to failure-mechanism:other.
"""
import json
from uuid import uuid4

from rca_contracts import (
    AssetSummary,
    CategoryCoverage,
    CoverageReport,
    DocumentEvidence,
    EvidencePackage,
    FailureModeCandidate,
    HierarchyPath,
    InvestigationPlan,
    ISO14224Context,
    OperatorLogEvidence,
    PlanStep,
    RcaConclusion,
    TagAnomaly,
    TagEvidence,
    WorkOrderEvidence,
)
from rca_llm import InMemoryResponseCache, LLMClientImpl, default_registry
from rca_llm.client import CompletionResult

from rca_agents.gather_graph import build_graph
from rca_agents.rca_graph import RcaAgent
from rca_agents.toolbox import FakeToolBox
from conftest import PROBE_RUN_ID, REF_TIME, leg_ctx, scripted_llm

_ANOMALY_KEY = "Review these per-tag summary"
_ANOMALIES = json.dumps({"anomalies": [
    {"tag_name": "P-101A.vibration_radial", "role": "vibration_radial",
     "summary": "rose to 6.6 mm/s", "severity": "critical"},
    {"tag_name": "P-101A.seal_flush_flow", "summary": "declined 4.5 L/min",
     "severity": "elevated"}]})


async def test_fake_toolbox_returns_modes_with_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    assert modes, "class should yield failure modes"
    elp = next(m for m in modes if m["code"] == "ELP")
    mech_ids = {x["id"] for x in elp["mechanisms"]}
    assert "failure-mechanism:seal-failure" in mech_ids


async def test_fake_toolbox_vib_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    vib = next(m for m in modes if m["code"] == "VIB")
    mech_ids = {x["id"] for x in vib["mechanisms"]}
    assert "failure-mechanism:cavitation" in mech_ids
    assert "failure-mechanism:misalignment" in mech_ids
    assert "failure-mechanism:bearing-wear" in mech_ids


async def test_fake_toolbox_ohe_mechanisms():
    tb = FakeToolBox()
    modes = await tb.failure_modes_for_class("equipment-class:bb1")
    ohe = next(m for m in modes if m["code"] == "OHE")
    mech_ids = {x["id"] for x in ohe["mechanisms"]}
    assert "failure-mechanism:lubrication-failure" in mech_ids
    assert "failure-mechanism:fouling" in mech_ids


# ---------------------------------------------------------------------------
# D14 gather-level: mechanisms must flow into the EvidencePackage (Sprint 6 WI2)
# ---------------------------------------------------------------------------

async def test_gather_enriches_evidence_package_with_mechanisms():
    """EvidencePackage.iso14224_context.applicable_failure_modes must carry mechanisms.

    Gather should populate this from ctx.toolbox.failure_modes_for_class (which returns
    modes WITH mechanisms) rather than the bare context.get("applicable_failure_modes").

    We simulate the real McpToolBox divergence: get_asset_context returns bare modes
    (no mechanisms), while failure_modes_for_class returns the rich fixture modes.
    Before the gather edit, the Evidence Package gets bare modes; after it, rich ones.
    """

    class _BareModeContext(FakeToolBox):
        """Simulate McpToolBox: get_asset_context returns modes WITHOUT mechanisms."""
        async def get_asset_context(self, canonical_id, iso14224_class=None):
            ctx = await super().get_asset_context(canonical_id, iso14224_class)
            # Strip mechanisms to mimic what the real KG context call returns today
            bare_modes = [{"code": m["code"], "id": m["id"], "name": m["name"]}
                          for m in ctx["applicable_failure_modes"]]
            return {**ctx, "applicable_failure_modes": bare_modes}

    plan = InvestigationPlan(
        plan_id=uuid4(), probe_run_id=PROBE_RUN_ID, version=1,
        asset_canonical_id="asset:refinery-gc:unit-101:p-101a",
        candidate_failure_modes=[
            FailureModeCandidate(iso14224_code="ELP", name="External leakage", rank=1,
                                 confidence=0.7, reasoning="seal flush low"),
            FailureModeCandidate(iso14224_code="VIB", name="Vibration", rank=2,
                                 confidence=0.5, reasoning="vib climbing")],
        steps=[
            PlanStep(step_id=uuid4(), step_type="tag_history", description="tags",
                     parameters={"roles": ["vibration_radial"]}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="work_orders", description="wos",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="documents", description="docs",
                     parameters={"query": "mechanical seal"}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="operator_logs", description="logs",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="kg_query", description="kg",
                     parameters={}, rationale="r"),
        ])

    seed = {"agent": "gather", "plan": plan.model_dump(mode="json"), "lookback_hours": 168}
    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=_BareModeContext())
    leg = await agent.run_leg(graph_state=seed, hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False
    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])

    modes = pkg.iso14224_context.applicable_failure_modes
    assert any(m.get("mechanisms") for m in modes), (
        "mechanisms must flow into the evidence package")
    elp = next((m for m in modes if m.get("code") == "ELP"), None)
    assert elp and any(
        x["id"] == "failure-mechanism:seal-failure" for x in elp["mechanisms"]
    )


# ---------------------------------------------------------------------------
# Sprint 6 WI2 D14 payoff: mechanism vocab coercion in _rank_validate_propose
# ---------------------------------------------------------------------------

_CID = "asset:refinery-gc:unit-101:p-101a"

# FakeToolBox modes carry 9 distinct mechanism ids across ELP/VIB/OHE — all in-vocab.
# ELP: seal-failure, corrosion, wear
# VIB: cavitation, misalignment, imbalance, bearing-wear, looseness
# OHE: lubrication-failure, bearing-wear (dup), overheating, fouling


class _MechRcaTransport:
    """Scripted RCA transport that lets callers inject a specific iso14224_mechanism
    in the rank response.  All other legs (fishbone, gaps, 5-whys) give minimal-valid
    responses so the agent reaches _rank_validate_propose without HITL stops."""

    def __init__(self, primary_mechanism: str) -> None:
        self._mech = primary_mechanism
        self._fw_calls = 0

    async def complete(self, *, model: str, rendered_prompt: str, temperature: float,
                       max_tokens: int, output_schema: dict | None) -> CompletionResult:
        content = self._route(rendered_prompt)
        return CompletionResult(content=content, model_version=f"{model}-test",
                                input_tokens=10, output_tokens=10)

    def _route(self, prompt: str) -> str:
        if "Ishikawa" in prompt:
            return json.dumps({"fishbone": [
                {"category": "Machine",
                 "causes": [{"cause": "worn mechanical seal", "supporting_evidence": []}]},
                {"category": "Method",
                 "causes": [{"cause": "insufficient seal flush flow"}]},
                {"category": "Measurement",
                 "causes": [{"cause": "vibration trending up"}]}]})
        if "whether the engineer should fill" in prompt:
            return json.dumps({"needs_hitl": False, "questions": []})
        if "Advance the 5 Whys" in prompt:
            self._fw_calls += 1
            root = self._fw_calls >= 3
            return json.dumps({
                "why_question": f"Why #{self._fw_calls}?",
                "answer": f"cause level {self._fw_calls}",
                "answer_source": "evidence_package", "grounded": True,
                "needs_human_knowledge": False, "is_root_cause": root,
                "supporting_evidence": []})
        if "Rank the failure hypotheses" in prompt:
            return json.dumps({
                "primary_hypothesis": {
                    "iso14224_failure_mode": "ELP",
                    "iso14224_mechanism": self._mech,
                    "confidence": 0.82,
                    "narrative": "mechanical seal degradation",
                    "supporting_evidence": []},
                "alternative_hypotheses": [],
                "recommended_actions": [{"action": "Replace seal",
                                         "rationale": "confirmed leak",
                                         "priority": "next_shutdown"}],
                "open_data_requests": []})
        return "{}"


def _rca_llm(mech: str) -> LLMClientImpl:
    return LLMClientImpl(registry=default_registry(), transport=_MechRcaTransport(mech),
                         cache=InMemoryResponseCache())


def _rca_pkg() -> EvidencePackage:
    """Evidence package with mechanism-carrying applicable_failure_modes (FakeToolBox data)."""
    modes = list(FakeToolBox.DEFAULT_FIXTURE["applicable_failure_modes"])
    return EvidencePackage(
        evidence_package_id=uuid4(), probe_run_id=PROBE_RUN_ID, canonical_id=_CID,
        investigated_failure_modes=["ELP", "VIB"], reference_time=REF_TIME, lookback_hours=168,
        asset=AssetSummary(canonical_id=_CID, name="P-101A",
                           iso14224_class="equipment-class:bb1"),
        location=HierarchyPath(plant_id="refinery-gc", unit="UNIT-101"),
        iso14224_context=ISO14224Context(equipment_class="equipment-class:bb1",
                                         applicable_failure_modes=modes),
        tag_evidence=TagEvidence(anomalies=[
            TagAnomaly(tag_name="P-101A.vibration_radial",
                       summary="climbing", severity="critical")]),
        work_order_evidence=WorkOrderEvidence(work_orders=[{"work_order_id": "WO-50012402"}]),
        document_evidence=DocumentEvidence(), operator_log_evidence=OperatorLogEvidence(),
        investigation_plan=InvestigationPlan(plan_id=uuid4(), probe_run_id=PROBE_RUN_ID,
                                             version=1, asset_canonical_id=_CID),
        coverage=CoverageReport(historian=CategoryCoverage(status="ok"),
                                cmms=CategoryCoverage(status="ok"),
                                documents=CategoryCoverage(status="ok"),
                                operator_log=CategoryCoverage(status="ok")),
        assembled_at=REF_TIME)


async def test_out_of_vocab_mechanism_coerced_to_other():
    """An LLM-chosen mechanism not in kg_valid_mechanisms is coerced to failure-mechanism:other.

    The EvidencePackage carries mechanism-rich applicable_failure_modes from FakeToolBox.
    The scripted rank response returns a fabricated mechanism id that is NOT in the vocab.
    After _rank_validate_propose the conclusion's primary_hypothesis must carry 'other'.
    """
    agent = RcaAgent()
    ctx = leg_ctx(_rca_llm("failure-mechanism:not-a-real-thing"), prompt="P-101A")
    seed = {"agent": "rca", "evidence_package": _rca_pkg().model_dump(mode="json")}
    leg = await agent.run_leg(graph_state=seed, hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    c = RcaConclusion.model_validate(leg.hitl_turn.proposed_conclusion)
    assert c.primary_hypothesis.iso14224_mechanism == "failure-mechanism:other", (
        f"OOV mechanism was not coerced: got {c.primary_hypothesis.iso14224_mechanism!r}")


async def test_in_vocab_mechanism_survives():
    """An LLM-chosen mechanism that IS in kg_valid_mechanisms passes through unchanged.

    'failure-mechanism:seal-failure' is in ELP's CAUSED_BY list in the FakeToolBox fixture.
    The coercion guard must leave it intact.
    """
    agent = RcaAgent()
    ctx = leg_ctx(_rca_llm("failure-mechanism:seal-failure"), prompt="P-101A")
    seed = {"agent": "rca", "evidence_package": _rca_pkg().model_dump(mode="json")}
    leg = await agent.run_leg(graph_state=seed, hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is True
    c = RcaConclusion.model_validate(leg.hitl_turn.proposed_conclusion)
    assert c.primary_hypothesis.iso14224_mechanism == "failure-mechanism:seal-failure", (
        f"In-vocab mechanism was incorrectly coerced: got "
        f"{c.primary_hypothesis.iso14224_mechanism!r}")
