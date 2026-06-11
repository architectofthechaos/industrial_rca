"""Idempotency (Sprint 2b §2.3) — THE headline acceptance item: a re-run with no source
change writes ZERO rows.

Proven two ways: the second project_to_mar over the same crawl returns all-zero counts AND
the InMemoryRepository's ``write_count`` (bumped on every upsert_asset/upsert_alias) is
unchanged — so the activity skipped the writes entirely, not just wrote the same values back.
project_to_kg gets the same treatment via the InMemoryHierarchyWriter's ``write_count``.
"""
from __future__ import annotations

from onb_helpers import HIERARCHY_CONNECTION_ID, PLANT_ID, hierarchy_connection

from rca_onboarding import activities as act


async def _crawl(deps):
    conn = hierarchy_connection()
    return await act._crawl_hierarchy_impl(deps, {
        "connection_id": conn.connection_id, "plant_id": conn.plant_id,
        "category": conn.category, "connector_type": conn.connector_type,
        "base_url": conn.base_url, "extra_config": conn.extra_config or {}})


async def test_project_to_mar_second_run_writes_nothing(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    result = await _crawl(deps)

    first = await act._project_to_mar_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)
    assert first.assets_new == 4
    writes_after_first = deps.repo.write_count
    assert writes_after_first == 8  # 4 assets + 4 bindings

    # Re-crawl (fresh, identical) and re-project: zero counts, zero new writes.
    result2 = await _crawl(deps)
    second = await act._project_to_mar_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result2.assets)
    assert second.assets_new == 0
    assert second.assets_updated == 0
    assert second.assets_decommissioned == 0
    assert second.bindings_pending_review == 0
    assert deps.repo.write_count == writes_after_first  # ZERO additional writes


async def test_project_to_mar_reuses_registered_asset_id(deps):
    """Regression: a register-seeded asset has its own asset_id under the canonical_id.
    Onboarding must reuse THAT id, not mint a fresh uuid5 (which would collide on
    uq_assets_canonical_id in Postgres). Caught by the live E2E run."""
    from uuid import UUID

    from rca_contracts import AssetDescriptor
    register_id = UUID("0190d3c9-0000-7000-8000-000000000001")  # P-101A's register asset_id
    canonical = "asset:refinery-gc:unit-101:p-101a"
    await deps.repo.upsert_connection(hierarchy_connection())
    await deps.repo.upsert_asset(AssetDescriptor(
        asset_id=register_id, canonical_id=canonical, tenant_id=deps.tenant_id,
        plant_id=PLANT_ID, iso14224_class="pump.centrifugal", iso14224_level=6,
        tag="P-101A", service="charge pump", criticality="A",
        manufacturer="Sulzer", model="AHLSTAR-A22-50", serial_number="SN-2018-00471",
        commissioned_at=None, decommissioned_at=None,
        location_description=None, description="charge pump"))

    result = await _crawl(deps)
    await act._project_to_mar_impl(deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)

    # the registered id is preserved (no second asset minted under the same canonical_id)
    again = await deps.repo.find_asset_by_canonical_id(deps.tenant_id, canonical)
    assert again is not None and again.asset_id == register_id
    # the binding points at the registered asset, not a uuid5-minted one
    binding = await deps.repo.find_active_alias(
        deps.tenant_id, HIERARCHY_CONNECTION_ID,
        next(a.vendor_id for a in result.assets if a.name == "P-101A"), valid_at=None)
    assert binding is not None and binding.asset_id == register_id


async def test_project_to_kg_second_run_writes_nothing(deps):
    result = await _crawl(deps)
    assert await act._project_to_kg_impl(deps, result.hierarchy_nodes) == 6
    writes_after_first = deps.kg.write_count  # 6 nodes + 5 edges
    assert writes_after_first == 11

    result2 = await _crawl(deps)
    assert await act._project_to_kg_impl(deps, result2.hierarchy_nodes) == 6  # nodes presented
    assert deps.kg.write_count == writes_after_first  # ZERO additional writes
    assert len(deps.kg.nodes) == 6
