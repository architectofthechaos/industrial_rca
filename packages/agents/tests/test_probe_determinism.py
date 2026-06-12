"""Sprint 4 WI7 (#15) — twice-run seeded probe yields a byte-identical RcaConclusion.

Determinism contract: with the same frozen ``reference_time`` (REF), the same scripted LLM
(``_ProbeTransport`` + InMemoryResponseCache), the same FakeToolBox fixture, and the same HITL
answers (``_drive_until_complete``), two independent full-workflow executions must produce the
*same* RcaConclusion. Agent-minted ids use ``det_uuid(probe_run_id, ...)`` and every timestamp
is sourced from ``ctx.reference_time``, so the conclusion is fully determined by its inputs.

We hash the *RcaConclusion*, NOT the EvidencePackage: ``FakeToolBox._prov`` stamps a fresh
``uuid4()`` into each provenance ``response_id``, so the EvidencePackage is intentionally not
byte-identical across runs. The RcaConclusion carries no such volatile field — its ids are
``det_uuid`` and its content is scripted — so it is the right determinism surface.

Reuses the hermetic harness from ``test_probe_workflow`` (same dir, pytest prepend import mode):
``_deps`` builds a FRESH ProbeActivityDeps (fresh in-memory repos) per run, ``_start_env`` brings
up the time-skipping Temporal env, and ``_drive_until_complete`` answers both HITL gates
identically.

IMPORTANT — the determinism *seed* includes ``probe_run_id``. The workflow mints it as
``inp.probe_run_id or str(workflow.uuid4())`` (workflow.py); ``workflow.uuid4`` is only
replay-deterministic *within one execution*, so two SEPARATE executions get different
probe_run_ids and therefore different ``det_uuid``-derived ids (conclusion_id, evidence id,
chain_id). That is correct for production but means the WI7 #15 reproducibility contract holds
only when the same inputs are supplied — including a fixed ``probe_run_id`` seed. So this test
pins ``probe_run_id`` to a constant for both runs (the API does the same minting upstream).
``test_probe_workflow``'s shared ``_run`` deliberately omits it (production behaviour), so we use
a small local runner here rather than mutate the shared helper.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

from rca_contracts import RcaConclusion

# Module-level helpers from the sibling end-to-end test; reused so both tests exercise the
# identical hermetic setup (scripted LLM, FakeToolBox, seeded graph, HITL driver, frozen REF).
from test_probe_workflow import REF, _deps, _drive_until_complete, _only_probe, _start_env

# Fixed determinism seed: the same probe_run_id for both runs => det_uuid yields the same ids.
SEED_PROBE_RUN_ID = UUID("0190d3c9-0000-7000-8000-00000000d151")


def _hash(conclusion: RcaConclusion) -> str:
    return hashlib.sha256(conclusion.model_dump_json().encode()).hexdigest()


async def _run_seeded(deps) -> None:
    """Run ONE full hermetic probe to completion via the REAL rca agent (rca_graph.build_graph,
    the default factory in ``_deps``), with a FIXED probe_run_id + frozen REF so the produced
    conclusion is fully determined by its inputs."""
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
                                   reference_time=REF, requested_by="eng@deepiq.com",
                                   probe_run_id=str(SEED_PROBE_RUN_ID)),
                id="probe-determinism-seeded", task_queue=task_queue())
            return await _drive_until_complete(handle, conclusion_approve=True)
    finally:
        await env.shutdown()


async def _run_once_capture_conclusion() -> RcaConclusion:
    deps = _deps()
    result = await _run_seeded(deps)
    assert result.status == "completed"
    conclusion = await deps.conclusions.get_for_probe(_only_probe(deps))
    assert conclusion is not None
    return conclusion


async def test_twice_run_seeded_probe_yields_identical_conclusion():
    first = await _run_once_capture_conclusion()
    second = await _run_once_capture_conclusion()

    h1, h2 = _hash(first), _hash(second)
    assert h1 == h2, (
        "RcaConclusion is not byte-identical across two seeded runs — a nondeterministic field "
        "leaked.\nrun1=" + first.model_dump_json() + "\nrun2=" + second.model_dump_json())

    # The deterministic id contract: same probe_run_id + same discriminators => same conclusion_id.
    assert first.conclusion_id == second.conclusion_id
