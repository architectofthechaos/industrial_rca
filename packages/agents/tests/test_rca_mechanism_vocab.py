"""D14 (Sprint 6 WI2) — failure_modes_for_class returns modes WITH mechanisms.

The FakeToolBox fixture carries real CAUSED_BY mechanism ids from the KG seed
(iso14224_bb1.cypher). McpToolBox delegates to kg.list_failure_modes_for_class.

Also covers that gather enriches the EvidencePackage's iso14224_context with the
mechanism-carrying modes from failure_modes_for_class (not the bare context modes).
"""
import json
from uuid import uuid4

from rca_contracts import (
    EvidencePackage,
    FailureModeCandidate,
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
