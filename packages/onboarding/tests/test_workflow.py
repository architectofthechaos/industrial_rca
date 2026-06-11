"""End-to-end workflow test via `temporalio.testing.WorkflowEnvironment` (Sprint 2b §2.6).

Runs the real OnboardingWorkflow + activities against the time-skipping test server, with the
activities backed by the in-memory deps bundle (set via ``set_activity_deps``). This is the
POST-equivalent path: start the workflow, await the OnboardingResult, assert 4 new / 0 updated
/ 0 decommissioned + a second-run idempotency check.

The time-skipping test server is downloaded/launched by temporalio; if that can't happen in
this environment (no network / sandbox), the whole module SKIPS cleanly — the same logic is
covered hermetically by test_activities / test_idempotency / test_decommission /
test_partial_coverage, which MUST pass.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from onb_helpers import PLANT_ID, hierarchy_connection

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from rca_onboarding.activities import ALL_ACTIVITIES, set_activity_deps
from rca_onboarding.models import OnboardingInput
from rca_onboarding.workflow import OnboardingWorkflow
# Reuse the production worker's sandbox runner (passes beartype/fastmcp through so the sandbox
# can prepare the workflow despite fastmcp's global beartype import claw).
from rca_onboarding.worker import _WORKFLOW_RUNNER

try:
    from temporalio.testing import WorkflowEnvironment
    _HAVE_ENV = True
except Exception:  # pragma: no cover - import-time guard
    _HAVE_ENV = False

pytestmark = pytest.mark.skipif(not _HAVE_ENV, reason="temporalio test env unavailable")


async def _start_env() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter)
    except Exception as exc:  # pragma: no cover - network/sandbox guard
        pytest.skip(f"time-skipping test server unavailable: {type(exc).__name__}: {exc}")


async def test_workflow_end_to_end(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    set_activity_deps(deps)
    task_queue = f"onboarding-test-{uuid4()}"

    env = await _start_env()
    try:
        client: Client = env.client
        async with Worker(client, task_queue=task_queue, workflows=[OnboardingWorkflow],
                          activities=ALL_ACTIVITIES, workflow_runner=_WORKFLOW_RUNNER):
            result = await client.execute_workflow(
                OnboardingWorkflow.run, OnboardingInput(plant_id=PLANT_ID),
                id=f"onboarding-{PLANT_ID}-{uuid4()}", task_queue=task_queue)
            assert result.status == "completed"
            assert result.counts.assets_new == 4
            assert result.counts.assets_updated == 0
            assert result.counts.assets_decommissioned == 0
            assert result.counts.hierarchy_nodes_upserted == 6
            assert result.per_category_results == {"hierarchy": "ok"}
            # The workflow wrote both the start and end coverage rows.
            run = await deps.runs.get_run(result.run_id)
            assert run is not None and run.status == "completed"

            # Second run over the same (unchanged) source: zero new writes.
            writes_before = deps.repo.write_count
            result2 = await client.execute_workflow(
                OnboardingWorkflow.run, OnboardingInput(plant_id=PLANT_ID),
                id=f"onboarding-{PLANT_ID}-{uuid4()}", task_queue=task_queue)
            assert result2.counts.assets_new == 0
            assert result2.counts.assets_updated == 0
            assert deps.repo.write_count == writes_before
    finally:
        await env.shutdown()
