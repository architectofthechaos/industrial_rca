"""Decommission-on-removal (Sprint 2b §2.3): an asset that disappears from the source on a
later crawl is reconciled — its binding superseded (system-initiated) and the asset flipped
to status='decommissioned'.

Run once over the full tree (4 assets incl. P-103A), then over a tree MISSING P-103A and
reconcile against the new crawl's seen vendor ids -> exactly one decommission.
"""
from __future__ import annotations

from uuid import uuid5, NAMESPACE_URL

from onb_helpers import (
    HIERARCHY_CONNECTION_ID,
    PLANT_ID,
    TENANT,
    hierarchy_connection,
    make_fake_af_app_without_p103a,
    make_http_factory,
)

from rca_onboarding import activities as act


def _conn_dict():
    c = hierarchy_connection()
    return {"connection_id": c.connection_id, "plant_id": c.plant_id, "category": c.category,
            "connector_type": c.connector_type, "base_url": c.base_url,
            "extra_config": c.extra_config or {}}


async def test_reconcile_decommissions_removed_asset(deps):
    await deps.repo.upsert_connection(hierarchy_connection())

    # First run: full tree, 4 assets projected.
    full = await act._crawl_hierarchy_impl(deps, _conn_dict())
    await act._project_to_mar_impl(deps, PLANT_ID, HIERARCHY_CONNECTION_ID, full.assets)
    p103a_id = uuid5(NAMESPACE_URL, "asset:refinery-gc:unit-201:p-103a")
    assert (TENANT, p103a_id) in deps.repo.assets
    assert deps.repo.status_of(TENANT, p103a_id) == "active"

    # Second run: tree without P-103A. Re-project, then reconcile against the new seen set.
    app2 = make_fake_af_app_without_p103a()
    deps2 = act.ActivityDeps(
        repo=deps.repo, kg=deps.kg, http_factory=make_http_factory(app2),
        threshold=deps.threshold, runs=deps.runs, tenant_id=deps.tenant_id)
    reduced = await act._crawl_hierarchy_impl(deps2, _conn_dict())
    assert {a.name for a in reduced.assets} == {"P-101A", "P-101B", "P-102A"}
    await act._project_to_mar_impl(deps2, PLANT_ID, HIERARCHY_CONNECTION_ID, reduced.assets)

    seen = [a.vendor_id for a in reduced.assets]
    decommissioned = await act._reconcile_decommission_impl(
        deps2, PLANT_ID, HIERARCHY_CONNECTION_ID, seen)
    assert decommissioned == 1
    assert deps.repo.status_of(TENANT, p103a_id) == "decommissioned"
    assert deps.repo.assets[(TENANT, p103a_id)].decommissioned_at is not None

    # P-103A's binding is superseded; the surviving three remain active.
    p103a_alias = next(a for a in deps.repo.aliases if a.asset_id == p103a_id)
    assert p103a_alias.resolution_status == "superseded"
    assert p103a_alias.valid_to is not None
    active = [a for a in deps.repo.aliases if a.valid_to is None]
    assert len(active) == 3


async def test_reconcile_no_op_when_nothing_removed(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    full = await act._crawl_hierarchy_impl(deps, _conn_dict())
    await act._project_to_mar_impl(deps, PLANT_ID, HIERARCHY_CONNECTION_ID, full.assets)
    seen = [a.vendor_id for a in full.assets]
    assert await act._reconcile_decommission_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, seen) == 0
