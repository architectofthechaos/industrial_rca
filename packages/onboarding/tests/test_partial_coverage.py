"""Partial coverage (Sprint 2b §2.2 / §2.6): a cmms connection whose health check fails is
recorded 'skipped:connection_unhealthy', and the run STILL completes the hierarchy work.

Tested at the orchestration-logic level (the workflow's per-category decision + activity call
order) so it runs hermetically without a Temporal server — the workflow uses the same pure
``health_decision`` helper. The full workflow-env path is covered (skip-if-unavailable) in
test_workflow.py.
"""
from __future__ import annotations

from onb_helpers import (
    HIERARCHY_CONNECTION_ID,
    PLANT_ID,
    cmms_connection,
    hierarchy_connection,
    make_http_factory,
)

from rca_onboarding import activities as act
from rca_onboarding.models import OnboardingInput
from rca_onboarding.workflow import health_decision


async def test_partial_coverage_cmms_unhealthy_hierarchy_proceeds(deps, fake_af_app):
    await deps.repo.upsert_connection(hierarchy_connection())
    await deps.repo.upsert_connection(cmms_connection())

    # A factory that reaches the fake AF app for the hierarchy host but raises for the cmms host.
    af_factory = make_http_factory(fake_af_app)

    def factory(base_url: str):
        if "maximo" in base_url:
            class _C:
                async def __aenter__(self_):
                    return self_
                async def __aexit__(self_, *a):
                    return False
                async def get(self_, path):
                    raise ConnectionError("maximo unreachable")
            return _C()
        return af_factory(base_url)

    d = act.ActivityDeps(
        repo=deps.repo, kg=deps.kg, http_factory=factory, threshold=deps.threshold,
        runs=deps.runs, tenant_id=deps.tenant_id)

    # --- replay the workflow's orchestration steps in order ---
    conns = await act._resolve_connections_impl(d, OnboardingInput(plant_id=PLANT_ID))
    assert len(conns) == 2

    per_category: dict[str, str] = {}
    health_by_id = {}
    for conn in conns:
        outcome = await act._health_check_connection_impl(d, conn)
        health_by_id[conn["connection_id"]] = outcome
        per_category[conn["category"]] = health_decision(outcome.ok)

    assert per_category["cmms"] == "skipped:connection_unhealthy"
    assert per_category["hierarchy"] == "ok"

    # Hierarchy work still done because the hierarchy connection is healthy.
    counts_total = None
    for conn in conns:
        if conn["category"] != "hierarchy" or not health_by_id[conn["connection_id"]].ok:
            continue
        result = await act._crawl_hierarchy_impl(d, conn)
        counts = await act._project_to_mar_impl(
            d, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)
        kg = await act._project_to_kg_impl(d, result.hierarchy_nodes)
        counts.hierarchy_nodes_upserted = kg
        counts_total = counts

    assert counts_total is not None
    assert counts_total.assets_new == 4
    assert counts_total.hierarchy_nodes_upserted == 6
