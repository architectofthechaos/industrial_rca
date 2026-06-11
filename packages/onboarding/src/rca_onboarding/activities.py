"""Onboarding activities (Sprint 2b Track 2) — all the side-effecting I/O the workflow drives.

Each Temporal activity (`@activity.defn`) is a thin wrapper over a pure ``_impl(deps, arg)``
coroutine, so tests exercise the real logic by calling ``_impl`` with an in-memory
``ActivityDeps`` bundle — no Temporal runtime required. The worker constructs the production
deps (PG repo, Neo4j hierarchy writer, httpx factory) and registers them via
``set_activity_deps`` before serving; the wrappers read that module-global ``_DEPS``.

Idempotency (the headline acceptance item) lives in ``project_to_mar`` / ``project_to_kg``:
both compare against the current stored state BEFORE writing, so a re-run with no source
change performs zero repo/KG writes. ``project_to_mar`` counts ``assets_updated`` only on a
real field change.

Simplification (documented): ``health_check_connection`` does a minimal HTTP reachability
probe against the connection's ``base_url`` rather than building the connector's FastMCP and
calling its ``test_connection`` tool. The Connections API owns the rich probe registry; the
onboarding package deliberately does NOT depend on connections_api (the negative-trigger
invariant — see connections_api/tests/test_negative_trigger.py), so duplicating the full
probe map here would couple the two. A reachability GET is sufficient to decide
skip-vs-crawl for the MVP.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from temporalio import activity

from rca_contracts import AssetDescriptor
from rca_kg.slugs import slug
from rca_mar.repository import AliasRow

from .models import HealthOutcome, OnboardingInput, ProjectionCounts

# The crawler models are needed at RUNTIME (the pydantic data converter resolves activity type
# hints via typing.get_type_hints, so these annotations must be importable). Activities are NOT
# sandboxed, so pulling the crawler package (-> fastmcp) here is fine; the workflow imports this
# module under workflow.unsafe.imports_passed_through() so the sandbox never re-imports fastmcp.
# The heavy `crawl` call itself is still imported lazily inside _crawl_hierarchy_impl.
from rca_connector_asset_hierarchy.models import (
    CrawlResult,
    DiscoveredAsset,
    DiscoveredHierarchyNode,
)

# attributes.Criticality word -> canonical A/B/C/D (matches the MAR seed _CRITICALITY map;
# AF only emits high/medium/low, so B is unreachable here — default C on anything else).
_CRITICALITY = {"high": "A", "medium": "C", "low": "D"}
# ISO 14224 leaf level for crawled assets — matches the refplant seed register (leaf == 6).
_LEAF_LEVEL = 6
_UNKNOWN_CLASS = "unknown.unclassified"

# KG label per discovered-hierarchy-node kind (Site/Area/Unit), matching Sprint 2a seed labels.
_KG_LABEL = {"site": "Site", "area": "Area", "unit": "Unit"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


HttpClientFactory = Callable[[str], httpx.AsyncClient]


@dataclass
class ActivityDeps:
    """Injected dependencies for the activities (constructed at worker startup / in tests)."""
    repo: Any                       # rca_mar AssetRepository
    kg: Any                         # rca_kg KgHierarchyWriter
    http_factory: HttpClientFactory  # base_url -> httpx.AsyncClient
    threshold: float                # MAR auto-accept confidence gate
    runs: Any                       # OnboardingRunsRepo
    tenant_id: UUID


# Module-level container set by the worker before serving; the @activity.defn wrappers read it.
_DEPS: ActivityDeps | None = None


def set_activity_deps(deps: ActivityDeps) -> None:
    global _DEPS
    _DEPS = deps


def _deps() -> ActivityDeps:
    if _DEPS is None:
        raise RuntimeError("activity deps not set; call set_activity_deps() at worker startup")
    return _DEPS


# ---------------------------------------------------------------------------- helpers


def _criticality(attributes: dict[str, str]) -> str:
    return _CRITICALITY.get(str(attributes.get("Criticality", "")).lower(), "C")


def _descriptor_for(deps: ActivityDeps, plant_id: str, asset: DiscoveredAsset,
                    asset_id: UUID | None = None) -> AssetDescriptor:
    # Reuse an already-registered asset's id when given (e.g. a register-seeded asset under the
    # same canonical_id); otherwise mint a deterministic id from the canonical_id. Minting a
    # fresh id for an already-registered canonical_id would violate uq_assets_canonical_id.
    asset_id = asset_id or uuid5(NAMESPACE_URL, asset.proposed_canonical_id)
    return AssetDescriptor(
        asset_id=asset_id,
        canonical_id=asset.proposed_canonical_id,
        tenant_id=deps.tenant_id,
        plant_id=plant_id,
        iso14224_class=asset.iso14224_class or _UNKNOWN_CLASS,
        iso14224_level=_LEAF_LEVEL,
        tag=asset.name,
        service=None,
        criticality=_criticality(asset.attributes),  # type: ignore[arg-type]
        manufacturer=asset.attributes.get("Manufacturer"),
        model=asset.attributes.get("Model"),
        serial_number=asset.attributes.get("SerialNumber"),
        commissioned_at=None, decommissioned_at=None,
        location_description=None,
        description=asset.attributes.get("ServiceDescription"))


def _descriptor_changed(existing: AssetDescriptor, proposed: AssetDescriptor) -> bool:
    """Compare the fields onboarding owns. Deliberately omits `service`/`location_description`
    (the crawl never populates them — `_descriptor_for` hardcodes them None) and the
    lifecycle/timestamp fields (status/decommissioned_at/created_at/updated_at) that other
    write paths own. When a future connector starts emitting `service`, add it here so a
    source-side change isn't silently ignored."""
    fields = ("canonical_id", "plant_id", "iso14224_class", "iso14224_level", "tag",
              "criticality", "manufacturer", "model", "serial_number", "description")
    return any(getattr(existing, f) != getattr(proposed, f) for f in fields)


def _mapping_source(asset: DiscoveredAsset) -> str:
    # The winning pattern-rule id is the mapping source; an unclassifiable asset (method
    # "none") is recorded as "crawl" so the binding still carries a meaningful provenance.
    return "crawl" if asset.iso14224_class_method == "none" else asset.iso14224_class_method


def _binding_changed(existing: AliasRow, asset: DiscoveredAsset, asset_id: UUID,
                     resolution_status: str) -> bool:
    """Has the binding's onboarding-owned content drifted from what the crawl now proposes?"""
    return (existing.asset_id != asset_id
            or existing.mapping_source != _mapping_source(asset)
            or existing.confidence != asset.iso14224_class_confidence
            or existing.vendor_path != asset.vendor_path
            or existing.resolution_status != resolution_status)


# ---------------------------------------------------------------------------- _impl bodies


async def _resolve_connections_impl(deps: ActivityDeps,
                                    inp: OnboardingInput) -> list[dict[str, Any]]:
    """Load the active connections to onboard for the plant; tag each with its category."""
    if inp.connection_ids:
        rows = []
        for cid in inp.connection_ids:
            conn = await deps.repo.get_connection(cid)
            if conn is not None and conn.status == "active" and conn.plant_id == inp.plant_id:
                rows.append(conn)
    else:
        rows = await deps.repo.list_connections(plant_id=inp.plant_id, status="active")
    return [
        {"connection_id": c.connection_id, "plant_id": c.plant_id, "category": c.category,
         "connector_type": c.connector_type, "base_url": c.base_url,
         "extra_config": c.extra_config or {}}
        for c in rows]


async def _health_check_connection_impl(deps: ActivityDeps,
                                        conn: dict[str, Any]) -> HealthOutcome:
    """Minimal reachability probe against the connection's base_url (see module docstring)."""
    base_url = conn["base_url"]
    # pi_af exposes /assetdatabases; everything else falls back to /openapi.json. Non-HTTP
    # transports (mqtt://) can't be probed this way -> report unhealthy with a clear reason.
    if not base_url.startswith(("http://", "https://")):
        return HealthOutcome(connection_id=conn["connection_id"], category=conn["category"],
                             ok=False, error=f"non-HTTP base_url not probeable: {base_url}")
    path = "/assetdatabases" if conn["connector_type"] == "pi_af" else "/openapi.json"
    try:
        async with deps.http_factory(base_url) as client:
            resp = await client.get(path)
            ok = resp.status_code < 500
            return HealthOutcome(
                connection_id=conn["connection_id"], category=conn["category"], ok=ok,
                error=None if ok else f"{path} -> HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001 — any connect/timeout error means unhealthy
        return HealthOutcome(connection_id=conn["connection_id"], category=conn["category"],
                             ok=False, error=f"{type(exc).__name__}: {exc}")


async def _crawl_hierarchy_impl(deps: ActivityDeps, conn: dict[str, Any]) -> CrawlResult:
    """Crawl the AF database behind this connection into discovered assets + hierarchy nodes."""
    from rca_connector_asset_hierarchy.crawler import crawl  # lazy: keeps fastmcp off import path
    database_name = conn["extra_config"]["database_name"]
    async with deps.http_factory(conn["base_url"]) as client:
        return await crawl(client, database_name=database_name, plant_id=conn["plant_id"],
                           max_depth=6)


async def _project_to_mar_impl(deps: ActivityDeps, plant_id: str, connection_id: str,
                               assets: list[DiscoveredAsset]) -> ProjectionCounts:
    """Project discovered assets into MAR (registry + bindings); zero writes on no change."""
    counts = ProjectionCounts()
    tenant = deps.tenant_id
    for asset in assets:
        existing_binding = await deps.repo.find_active_alias(
            tenant, connection_id, asset.vendor_id, valid_at=None)
        existing_asset = await deps.repo.find_asset_by_canonical_id(
            tenant, asset.proposed_canonical_id)

        # Reuse the registered asset's id (e.g. a register-seeded P-101A) so we update it in
        # place rather than inserting a colliding canonical_id with a freshly-minted id.
        existing_asset_id = existing_asset.asset_id if existing_asset is not None else None
        proposed = _descriptor_for(deps, plant_id, asset, asset_id=existing_asset_id)
        asset_id = proposed.asset_id
        resolution_status = ("auto_resolved"
                             if asset.iso14224_class_confidence >= deps.threshold
                             else "pending_review")

        # --- asset registry: insert new, update on change, else no-op (idempotent) ---
        asset_was_new = existing_asset is None
        asset_changed = (not asset_was_new) and _descriptor_changed(existing_asset, proposed)
        if asset_was_new or asset_changed:
            await deps.repo.upsert_asset(proposed)

        # --- binding: write only when missing or drifted (zero-row-write on no change) ---
        binding_was_new = existing_binding is None
        binding_changed = (not binding_was_new) and _binding_changed(
            existing_binding, asset, asset_id, resolution_status)
        if binding_was_new or binding_changed:
            await deps.repo.upsert_alias(_alias_for(
                deps, asset, asset_id, connection_id, resolution_status))

        # --- counts (each asset contributes to at most one of new/updated) ---
        if asset_was_new and binding_was_new:
            counts.assets_new += 1               # brand-new asset + its first binding
        elif asset_changed or binding_was_new or binding_changed:
            counts.assets_updated += 1            # attached a binding, or content drifted
        # else: existing asset + existing binding, both unchanged -> no-op, count nothing.

        # pending_review only counts when we actually (re)wrote a pending binding.
        if (binding_was_new or binding_changed) and resolution_status == "pending_review":
            counts.bindings_pending_review += 1
    return counts


def _alias_for(deps: ActivityDeps, asset: DiscoveredAsset, asset_id: UUID, connection_id: str,
               resolution_status: str) -> AliasRow:
    candidate_alternatives = None
    if resolution_status == "pending_review":
        candidate_alternatives = [{
            "canonical_id": asset.proposed_canonical_id,
            "confidence": asset.iso14224_class_confidence,
            "method": asset.iso14224_class_method,
        }]
    return AliasRow(
        asset_id=asset_id, tenant_id=deps.tenant_id, connection_id=connection_id,
        external_id=asset.vendor_id, valid_from=_utcnow(), valid_to=None,
        mapping_source=_mapping_source(asset), confidence=asset.iso14224_class_confidence,
        resolution_status=resolution_status, resolved_by="system",
        vendor_path=asset.vendor_path, vendor_metadata={"attributes": asset.attributes},
        candidate_alternatives=candidate_alternatives)


async def _project_to_kg_impl(deps: ActivityDeps,
                              hierarchy_nodes: list[DiscoveredHierarchyNode]) -> int:
    """Upsert Site/Area/Unit nodes + CONTAINS edges into the KG (NO Asset nodes; Sprint 3)."""
    if not hierarchy_nodes:
        return 0
    # Map each node's vendor_id -> its minted KG id so a child's parent edge points at the
    # parent's KG id (the crawl gives parent_vendor_id, not the minted id).
    minted: dict[str, str] = {}
    for node in hierarchy_nodes:
        minted[node.vendor_id] = _mint_kg_id(node.kind, node.plant_id, node.name)
    payload = []
    for node in hierarchy_nodes:
        parent_id = minted.get(node.parent_vendor_id) if node.parent_vendor_id else None
        payload.append({
            "id": minted[node.vendor_id], "label": _KG_LABEL[node.kind], "name": node.name,
            "plant_id": node.plant_id, "parent_id": parent_id})
    return await deps.kg.upsert_hierarchy_nodes(payload)


def _mint_kg_id(kind: str, plant_id: str, name: str) -> str:
    if kind == "site":
        return f"site:{slug(plant_id)}"
    return f"{kind}:{slug(plant_id)}:{slug(name)}"


async def _reconcile_decommission_impl(deps: ActivityDeps, plant_id: str, connection_id: str,
                                       seen_vendor_ids: list[str]) -> int:
    """Decommission assets whose bindings vanished from the source on this crawl.

    `plant_id` is currently unused (the connection_id scopes the alias query and encodes the
    plant) — kept in the signature for symmetry with the other activities and reserved for a
    future plant-scoped reconciliation (e.g. cross-connection consistency checks)."""
    seen = set(seen_vendor_ids)
    tenant = deps.tenant_id
    decommissioned = 0
    active = await deps.repo.list_active_aliases_for_connection(tenant, connection_id)
    for alias in active:
        if alias.external_id in seen:
            continue
        # supersede the orphaned binding (system-initiated) + flip the asset to decommissioned.
        if alias.alias_id is not None:
            await deps.repo.supersede_binding(alias.alias_id, system_initiated=True)
        await deps.repo.decommission_asset(tenant, alias.asset_id)
        decommissioned += 1
    return decommissioned


async def _write_coverage_report_impl(deps: ActivityDeps, run: dict[str, Any]) -> None:
    """Upsert the onboarding_runs row (start: status=running; end: completed/failed)."""
    if run.get("phase") == "start":
        await deps.runs.create_run(
            run_id=run["run_id"], workflow_id=run["workflow_id"], plant_id=run["plant_id"],
            connection_ids=run.get("connection_ids"),
            started_at=datetime.fromisoformat(run["started_at"]))
    else:
        await deps.runs.complete_run(
            run_id=run["run_id"], status=run["status"],
            per_category_results=run.get("per_category_results", {}),
            counts=run.get("counts", {}), errors=run.get("errors", []),
            completed_at=datetime.fromisoformat(run["completed_at"]))


# ---------------------------------------------------------------------------- @activity.defn


@activity.defn
async def resolve_connections(inp: OnboardingInput) -> list[dict[str, Any]]:
    return await _resolve_connections_impl(_deps(), inp)


@activity.defn
async def health_check_connection(conn: dict[str, Any]) -> HealthOutcome:
    return await _health_check_connection_impl(_deps(), conn)


@activity.defn
async def crawl_hierarchy(conn: dict[str, Any]) -> CrawlResult:
    return await _crawl_hierarchy_impl(_deps(), conn)


@activity.defn
async def project_to_mar(plant_id: str, connection_id: str,
                         assets: list[DiscoveredAsset]) -> ProjectionCounts:
    return await _project_to_mar_impl(_deps(), plant_id, connection_id, assets)


@activity.defn
async def project_to_kg(hierarchy_nodes: list[DiscoveredHierarchyNode]) -> int:
    return await _project_to_kg_impl(_deps(), hierarchy_nodes)


@activity.defn
async def reconcile_decommission(plant_id: str, connection_id: str,
                                 seen_vendor_ids: list[str]) -> int:
    return await _reconcile_decommission_impl(_deps(), plant_id, connection_id, seen_vendor_ids)


@activity.defn
async def write_coverage_report(run: dict[str, Any]) -> None:
    await _write_coverage_report_impl(_deps(), run)


ALL_ACTIVITIES: list[Callable[..., Any]] = [
    resolve_connections, health_check_connection, crawl_hierarchy, project_to_mar,
    project_to_kg, reconcile_decommission, write_coverage_report,
]

__all__ = [
    "ActivityDeps", "set_activity_deps", "ALL_ACTIVITIES",
    "resolve_connections", "health_check_connection", "crawl_hierarchy", "project_to_mar",
    "project_to_kg", "reconcile_decommission", "write_coverage_report",
    # _impl exports for direct (Temporal-free) testing.
    "_resolve_connections_impl", "_health_check_connection_impl", "_crawl_hierarchy_impl",
    "_project_to_mar_impl", "_project_to_kg_impl", "_reconcile_decommission_impl",
    "_write_coverage_report_impl",
]
