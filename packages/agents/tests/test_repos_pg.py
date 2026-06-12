import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RCA_DB") != "1",
                                reason="requires Postgres (task infra:up)")


@pytest.mark.asyncio
async def test_runs_repo_create_get_update_idempotent():
    from datetime import datetime, timezone

    from rca_agents.repos_pg import PgProbeRunsRepo

    repo = PgProbeRunsRepo()
    rid = uuid.uuid4()
    ref = datetime(2026, 3, 30, tzinfo=timezone.utc)
    await repo.create_run(probe_run_id=rid, workflow_id=f"probe-{rid}", plant_id="refinery-gc",
                          prompt="RCA on P-101A", reference_time=ref, requested_by="pilot",
                          started_at=ref)
    await repo.create_run(probe_run_id=rid, workflow_id=f"probe-{rid}", plant_id="refinery-gc",
                          prompt="RCA on P-101A", reference_time=ref, requested_by="pilot",
                          started_at=ref)  # idempotent
    run = await repo.get_run(rid)
    assert run is not None and run["plant_id"] == "refinery-gc" and run["status"] == "running"
    await repo.update_status(rid, status="completed", phase="closed",
                             final_canonical_id="asset:refinery-gc:unit-101:p-101a",
                             completed_at=ref)
    run = await repo.get_run(rid)
    assert run["status"] == "completed" and run["phase"] == "closed"


@pytest.mark.asyncio
async def test_memory_repo_snapshot_get_append():
    from datetime import datetime, timezone

    from rca_agents.repos_pg import PgProbeMemoryRepo, PgProbeRunsRepo

    rid = uuid.uuid4()
    ref = datetime(2026, 3, 30, tzinfo=timezone.utc)
    # a memory row FKs to probe_runs — create the run first
    await PgProbeRunsRepo().create_run(probe_run_id=rid, workflow_id=f"probe-{rid}",
        plant_id="refinery-gc", prompt="p", reference_time=ref, requested_by="x", started_at=ref)
    mem = PgProbeMemoryRepo()
    await mem.snapshot(rid, {"current_plan": {"steps": []}, "token_usage": {"input_tokens": 3}})
    await mem.append_turn(rid, {"turn_id": "t1"})
    await mem.append_response(rid, {"turn_id": "t1", "answer": "yes"})
    got = await mem.get(rid)
    assert got is not None and got.get("current_plan") == {"steps": []}


@pytest.mark.asyncio
async def test_evidence_and_conclusion_roundtrip_idempotent():
    from datetime import datetime, timezone

    from rca_contracts import (
        FiveWhysChain,
        FiveWhysStep,
        FishboneCategory,
        FishboneCause,
        RankedHypothesis,
        RcaConclusion,
        RecommendedAction,
    )

    from rca_agents.base import det_uuid
    from rca_agents.repos_pg import (
        PgEvidencePackageRepo,
        PgProbeRunsRepo,
        PgRcaConclusionRepo,
    )
    # Reuse the proven EvidencePackage factory from the rca-agent test module (same tests dir,
    # on sys.path under pytest prepend import mode). It builds a fully valid package keyed on
    # conftest.PROBE_RUN_ID. We rebind probe_run_id to a fresh UUID so the row is unique.
    from test_rca_agent import _evidence_package

    ref = datetime(2026, 3, 30, tzinfo=timezone.utc)
    rid = uuid.uuid4()
    pkg = _evidence_package().model_copy(update={
        "evidence_package_id": uuid.uuid4(), "probe_run_id": rid, "assembled_at": ref})

    # evidence_packages.probe_run_id + rca_conclusions.probe_run_id FK probe_runs — create it.
    await PgProbeRunsRepo().create_run(
        probe_run_id=rid, workflow_id=f"probe-{rid}", plant_id="refinery-gc", prompt="p",
        reference_time=ref, requested_by="x", started_at=ref)

    # A minimal valid RcaConclusion sharing this probe_run_id + evidence_package_id.
    concl = RcaConclusion(
        conclusion_id=det_uuid(rid, "concl"), probe_run_id=rid,
        evidence_package_id=pkg.evidence_package_id, canonical_id=pkg.canonical_id,
        primary_hypothesis=RankedHypothesis(
            rank=1, iso14224_failure_mode="ELP",
            iso14224_mechanism="failure-mechanism:seal-failure", confidence=0.9,
            narrative="mechanical seal leak"),
        fishbone=[FishboneCategory(category="Machine",
                                   causes=[FishboneCause(cause="worn seal")])],
        five_whys=FiveWhysChain(
            chain_id=det_uuid(rid, "fw"), initial_problem="seal leak",
            terminal_root_cause="dry-running seal face", confidence=0.9,
            steps=[FiveWhysStep(rank=i, why_question="w", answer="a",
                                answer_source="agent_inference") for i in (1, 2, 3)]),
        recommended_actions=[RecommendedAction(action="replace seal", rationale="leak",
                                               priority="next_shutdown")],
        agent_version="rca_agent_v1", generated_at=ref)

    ev = PgEvidencePackageRepo()
    cc = PgRcaConclusionRepo()

    await ev.put(pkg)
    await ev.put(pkg)  # idempotent
    assert (await ev.get(pkg.evidence_package_id)).model_dump(mode="json") \
        == pkg.model_dump(mode="json")
    assert (await ev.get_for_probe(pkg.probe_run_id)).evidence_package_id \
        == pkg.evidence_package_id

    await cc.put(concl, status="proposed")
    await cc.put(concl, status="proposed")  # idempotent
    assert (await cc.get(concl.conclusion_id)).model_dump(mode="json") \
        == concl.model_dump(mode="json")
    assert (await cc.get_for_probe(concl.probe_run_id)).conclusion_id == concl.conclusion_id
