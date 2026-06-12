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
