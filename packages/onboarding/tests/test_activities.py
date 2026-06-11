"""Activity-level tests (Sprint 2b acceptance) — exercise each `_impl` directly, no Temporal.

The fake PI AF crawl yields 4 pump assets (all confidence 0.95 -> auto_resolved) under a
6-node hierarchy (1 site + 2 areas + 3 units). The mystery variant adds an unclassifiable
asset (confidence 0.0 -> pending_review) to cover the low-confidence binding path.
"""
from __future__ import annotations

from uuid import uuid5, NAMESPACE_URL

from onb_helpers import (
    CMMS_CONNECTION_ID,
    HIERARCHY_CONNECTION_ID,
    PLANT_ID,
    TENANT,
    hierarchy_connection,
    make_http_factory,
)

from fake_af import make_fake_af_app

from rca_onboarding import activities as act
from rca_onboarding.models import OnboardingInput


async def _crawl(deps, conn) -> list:
    conn_dict = {
        "connection_id": conn.connection_id, "plant_id": conn.plant_id,
        "category": conn.category, "connector_type": conn.connector_type,
        "base_url": conn.base_url, "extra_config": conn.extra_config or {}}
    return await act._crawl_hierarchy_impl(deps, conn_dict)


async def test_resolve_connections_filters_active(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    # A non-active connection in the same plant must be excluded.
    pending = hierarchy_connection()
    pending = type(pending)(**{**pending.__dict__,
                               "connection_id": "refinery-gc.document.sp-default",
                               "category": "document", "status": "pending"})
    await deps.repo.upsert_connection(pending)

    rows = await act._resolve_connections_impl(deps, OnboardingInput(plant_id=PLANT_ID))
    ids = {r["connection_id"] for r in rows}
    assert ids == {HIERARCHY_CONNECTION_ID}
    assert rows[0]["category"] == "hierarchy"
    assert rows[0]["extra_config"]["database_name"] == "Refinery-GC"


async def test_resolve_connections_named_subset(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    rows = await act._resolve_connections_impl(
        deps, OnboardingInput(plant_id=PLANT_ID, connection_ids=[HIERARCHY_CONNECTION_ID]))
    assert [r["connection_id"] for r in rows] == [HIERARCHY_CONNECTION_ID]


async def test_health_check_ok(deps):
    conn = hierarchy_connection()
    outcome = await act._health_check_connection_impl(deps, {
        "connection_id": conn.connection_id, "category": conn.category,
        "connector_type": conn.connector_type, "base_url": conn.base_url})
    assert outcome.ok is True
    assert outcome.category == "hierarchy"


async def test_health_check_fail_unreachable(deps):
    # An unreachable upstream surfaces as ok=False with the error captured (not an exception).
    def raising_factory(base_url):
        class _C:
            async def __aenter__(self_):
                return self_
            async def __aexit__(self_, *a):
                return False
            async def get(self_, path):
                raise ConnectionError("connection refused")
        return _C()

    bad_deps = act.ActivityDeps(
        repo=deps.repo, kg=deps.kg, http_factory=raising_factory, threshold=deps.threshold,
        runs=deps.runs, tenant_id=deps.tenant_id)
    outcome = await act._health_check_connection_impl(bad_deps, {
        "connection_id": CMMS_CONNECTION_ID, "category": "cmms",
        "connector_type": "maximo", "base_url": "http://maximo-unreachable"})
    assert outcome.ok is False
    assert "ConnectionError" in (outcome.error or "")


async def test_health_check_non_http_base_url(deps):
    outcome = await act._health_check_connection_impl(deps, {
        "connection_id": "refinery-gc.historian.uns-default", "category": "historian",
        "connector_type": "uns", "base_url": "mqtt://localhost:1883"})
    assert outcome.ok is False
    assert "non-HTTP" in (outcome.error or "")


async def test_crawl_hierarchy_returns_four_assets(deps):
    result = await _crawl(deps, hierarchy_connection())
    assert len(result.assets) == 4
    assert len(result.hierarchy_nodes) == 6
    assert {a.name for a in result.assets} == {"P-101A", "P-101B", "P-102A", "P-103A"}


async def test_project_to_mar_first_run(deps):
    await deps.repo.upsert_connection(hierarchy_connection())
    result = await _crawl(deps, hierarchy_connection())
    counts = await act._project_to_mar_impl(
        deps, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)
    assert counts.assets_new == 4
    assert counts.assets_updated == 0
    assert counts.bindings_pending_review == 0  # all 0.95 >= 0.92
    assert len(deps.repo.assets) == 4
    assert len([a for a in deps.repo.aliases if a.valid_to is None]) == 4

    # Criticality mapping: P-101A high->A, P-102A medium->C, P-103A low->D.
    by_canon = {a.canonical_id: a for a in deps.repo.assets.values()}
    assert by_canon["asset:refinery-gc:unit-101:p-101a"].criticality == "A"
    assert by_canon["asset:refinery-gc:unit-102:p-102a"].criticality == "C"
    assert by_canon["asset:refinery-gc:unit-201:p-103a"].criticality == "D"
    # Deterministic asset_id from canonical_id.
    expected_id = uuid5(NAMESPACE_URL, "asset:refinery-gc:unit-101:p-101a")
    assert by_canon["asset:refinery-gc:unit-101:p-101a"].asset_id == expected_id
    # Binding provenance.
    a101 = next(a for a in deps.repo.aliases
                if a.external_id and a.valid_to is None and a.asset_id == expected_id)
    assert a101.mapping_source == "rule:pump_template_name"
    assert a101.resolution_status == "auto_resolved"
    assert a101.resolved_by == "system"
    assert a101.vendor_metadata["attributes"]["Manufacturer"] == "Sulzer"


async def test_project_to_mar_low_confidence_is_pending_review(deps):
    app = make_fake_af_app(include_mystery=True)
    deps2 = act.ActivityDeps(
        repo=deps.repo, kg=deps.kg, http_factory=make_http_factory(app),
        threshold=deps.threshold, runs=deps.runs, tenant_id=deps.tenant_id)
    await deps2.repo.upsert_connection(hierarchy_connection())
    result = await _crawl(deps2, hierarchy_connection())
    counts = await act._project_to_mar_impl(
        deps2, PLANT_ID, HIERARCHY_CONNECTION_ID, result.assets)
    assert counts.assets_new == 5
    assert counts.bindings_pending_review == 1
    mystery = next(a for a in deps2.repo.aliases
                   if a.vendor_metadata
                   and a.vendor_metadata["attributes"].get("Manufacturer") == "Acme")
    assert mystery.resolution_status == "pending_review"
    assert mystery.mapping_source == "crawl"
    assert mystery.candidate_alternatives[0]["confidence"] == 0.0
    # The unclassifiable asset is registered with the fallback class.
    asset = deps2.repo.assets[(TENANT, mystery.asset_id)]
    assert asset.iso14224_class == "unknown.unclassified"


async def test_project_to_kg_upserts_hierarchy(deps):
    result = await _crawl(deps, hierarchy_connection())
    n = await act._project_to_kg_impl(deps, result.hierarchy_nodes)
    assert n == 6
    assert deps.kg.nodes["site:refinery-gc"]["label"] == "Site"
    assert deps.kg.nodes["area:refinery-gc:area-100"]["label"] == "Area"
    assert deps.kg.nodes["unit:refinery-gc:unit-101"]["label"] == "Unit"
    # CONTAINS edges from minted parent ids (vendor->minted mapped within the node set).
    assert ("site:refinery-gc", "area:refinery-gc:area-100") in deps.kg.edges
    assert ("area:refinery-gc:area-100", "unit:refinery-gc:unit-101") in deps.kg.edges
    assert ("area:refinery-gc:area-200", "unit:refinery-gc:unit-201") in deps.kg.edges


async def test_write_coverage_report_persists(deps):
    await act._write_coverage_report_impl(deps, {
        "phase": "start", "run_id": "11111111-1111-1111-1111-111111111111",
        "workflow_id": "wf-1", "plant_id": PLANT_ID, "connection_ids": None,
        "started_at": "2026-06-11T00:00:00+00:00"})
    rec = await deps.runs.get_run("11111111-1111-1111-1111-111111111111")
    assert rec is not None and rec.status == "running"

    await act._write_coverage_report_impl(deps, {
        "phase": "end", "run_id": "11111111-1111-1111-1111-111111111111",
        "status": "completed", "per_category_results": {"hierarchy": "ok"},
        "counts": {"assets_new": 4}, "errors": [],
        "completed_at": "2026-06-11T00:05:00+00:00"})
    rec = await deps.runs.get_run("11111111-1111-1111-1111-111111111111")
    assert rec.status == "completed"
    assert rec.counts == {"assets_new": 4}
    assert rec.per_category_results == {"hierarchy": "ok"}
