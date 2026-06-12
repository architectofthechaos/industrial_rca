"""Composition root: mount MAR + KG(+asset_graph) + connector MCP servers into one FastMCP.

This is the ONLY agents-package module allowed to import connector/MAR/KG servers (it is the
entrypoint, not agent logic — §8 scope note). The worker builds the host, wraps it in a
fastmcp.Client, and hands the client to McpToolBox. Swapping in-process for HTTP is a Client
construction change here; nothing in the toolbox or agents changes.

Process isolation (D9 / Risk #5)
--------------------------------
For the pilot, all six entity servers are mounted into ONE FastMCP process (operational
simplicity). FastMCP isolates tool failures per-request — a raising/failing tool returns an
error to the caller and the host stays up (test: ``test_host_health.py``) — and every tool
already returns a typed ``ToolResponse.error`` rather than crashing. ``GET /health`` reports
host liveness + per-mount readiness.

Path to one-process-per-server for production (NOT implemented this sprint): each
``make_*_mcp`` factory already stands alone, so a connector can be split into its own process by
serving it standalone (``make_tag_mcp(...).run(transport="http", port=...)``) and registering
that URL as the source's active connection in ``connections_api`` — the dynamic
``RegistryConnectionRouter`` (WI4) then routes to it with no code change. The agent/worker side
is unaffected (it only ever speaks MCP to the host URL). Splitting is therefore config +
deployment, not a rewrite; do it when a single crashing source must not affect the others or
when per-source scaling/SLAs diverge.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from fastmcp import FastMCP
from rca_connector_documents.server import make_document_mcp
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp
from rca_connector_sdk import (
    CanonicalSlugAssetGateway,
    ConnectionInfo,
    ConnectionRouter,
    MarAssetGateway,
    RegistryConnectionRouter,
    StaticConnectionRouter,
)
from rca_kg.assets import Neo4jAssetGraph
from rca_kg.queries import Neo4jGateway
from rca_kg.server import make_kg_mcp
from rca_mar.config import make_engine, make_session_factory
from rca_mar.repository_pg import PostgresRepository
from rca_mar.server import make_mar_mcp

PLANT_ID = os.environ.get("PLANT_ID", "refinery-gc")
TENANT_ID = UUID(os.environ.get("TENANT_ID", "0190d3c9-0000-7000-8000-0000000000ff"))
HISTORIAN_SIM_URL = os.environ.get("HISTORIAN_SIM_URL", "http://127.0.0.1:8001")
CMMS_SIM_URL = os.environ.get("CMMS_SIM_URL", "http://127.0.0.1:8002")
DOCUMENT_SIM_URL = os.environ.get("DOCUMENT_SIM_URL", "http://127.0.0.1:8004")


def _dev_connections() -> list[ConnectionInfo]:
    """One active connection per category for the reference plant (Phase 1: one source/category).

    operator_log shares the historian sim (PI event frames live alongside the PI historian);
    they are distinct categories so each still resolves to its own ConnectionInfo. The un-seeded /
    registry-unreachable fallback (mirrors scripts/run_mcp_host.py's dev router)."""
    return [
        ConnectionInfo(connection_id=f"{PLANT_ID}.historian.pi-main", plant_id=PLANT_ID,
                       category="historian", connector_type="pi_historian",
                       base_url=HISTORIAN_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.operator_log.pi-event-frames", plant_id=PLANT_ID,
                       category="operator_log", connector_type="pi_event_frames",
                       base_url=HISTORIAN_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.cmms.maximo-main", plant_id=PLANT_ID,
                       category="cmms", connector_type="maximo", base_url=CMMS_SIM_URL),
        ConnectionInfo(connection_id=f"{PLANT_ID}.document.sharepoint-main", plant_id=PLANT_ID,
                       category="document", connector_type="sharepoint", base_url=DOCUMENT_SIM_URL),
    ]


def _static_dev_router() -> StaticConnectionRouter:
    """Boot-time static snapshot (tests + dev fallback)."""
    return StaticConnectionRouter(_dev_connections())


def _registry_router() -> RegistryConnectionRouter:
    """D10: dynamic per-request router over the live connections registry. Each ``active(...)``
    queries MAR ``list_connections(status='active')`` for the (plant, category), so connect/
    disconnect takes effect on the next tool call with no worker restart. If the registry is
    UNREACHABLE the provider falls back to the static dev connection for that scope (so a dev box
    without connections_api still works); an *empty* (reachable) result is NOT masked — it
    correctly yields NoActiveConnection so disable->reroute is observable."""
    repo = PostgresRepository(make_session_factory(make_engine()))
    dev = {(c.plant_id, c.category): c for c in _dev_connections()}

    async def provider(plant_id: str, category: str) -> list[ConnectionInfo]:
        try:
            rows = await repo.list_connections(plant_id=plant_id, category=category,
                                               status="active")
        except Exception:  # noqa: BLE001 — registry unreachable -> dev fallback for this scope
            c = dev.get((plant_id, category))
            return [c] if c else []
        return [ConnectionInfo(connection_id=r.connection_id, plant_id=r.plant_id,
                               category=r.category, connector_type=r.connector_type,
                               base_url=r.base_url, extra_config=r.extra_config or {})
                for r in rows]

    return RegistryConnectionRouter(provider)


# Back-compat alias (D6 boot-time snapshot); the live host now defaults to the dynamic router.
async def router_from_connections() -> ConnectionRouter:
    return _registry_router()


async def build_entity_host(*, router: ConnectionRouter | None = None,
                            mar_repo: Any = None, asset_graph: Any = None) -> FastMCP:
    """Mount all six entity MCP servers into one host (no prefix — verbatim tool names).

    Defaults wire the production stores (Postgres MAR repo, Neo4j KG gateway + asset graph) and
    a registry-derived router; tests inject InMemoryRepository/InMemoryAssetGraph + a static
    router for a hermetic, network-free build.
    """
    if router is None:
        router = await router_from_connections()
    gateway = CanonicalSlugAssetGateway()
    if mar_repo is None:
        mar_repo = PostgresRepository(make_session_factory(make_engine()))
    cmms_gateway = MarAssetGateway(repo=mar_repo, tenant_id=TENANT_ID)   # D13/WI1 — MAR-backed CMMS handle
    if asset_graph is None:
        asset_graph = Neo4jAssetGraph()
    host = FastMCP("entity-mcp-host")
    host.mount(make_mar_mcp(repo=mar_repo, tenant_id=TENANT_ID))
    host.mount(make_kg_mcp(gateway=Neo4jGateway(), asset_graph=asset_graph))
    host.mount(make_tag_mcp(router=router, assets=gateway, default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_operator_log_mcp(router=router, assets=gateway,
                                     default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_work_order_mcp(router=router, assets=cmms_gateway, default_base_url=CMMS_SIM_URL))
    host.mount(make_document_mcp(router=router, assets=gateway, default_base_url=DOCUMENT_SIM_URL))
    _register_health(host)
    return host


# Per-mount readiness for /health: each expected entity mount + the tool-name prefix that proves
# it loaded. (D9 — host + per-mount status.)
_EXPECTED_MOUNTS = {
    "asset": "asset.",        # MAR
    "kg": "kg.",              # KG (+ asset layer)
    "tag": "tag.",            # PI historian
    "operator_log": "operator_log.",
    "work_order": "work_order.",   # Maximo
    "document": "document.",       # SharePoint/docs
}


def _register_health(host: FastMCP) -> None:
    """GET /health — host liveness + per-mount readiness (D9, Risk #5).

    Reports each expected entity mount as ready iff its tools loaded into the host. 200 when all
    mounts are present (degraded/503 if any is missing — a misconfigured/failed mount). This is a
    lightweight readiness check (mounts loaded), distinct from each connector's own
    ``test_connection`` (upstream reachability)."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    @host.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        try:
            tool_names = [t.name for t in await host.list_tools()]
        except Exception as exc:  # noqa: BLE001 — a broken host is unhealthy, never raise
            return JSONResponse({"status": "unhealthy", "error": f"{type(exc).__name__}: {exc}"},
                                status_code=503)
        mounts = {name: any(t.startswith(prefix) for t in tool_names)
                  for name, prefix in _EXPECTED_MOUNTS.items()}
        ok = all(mounts.values())
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "mounts": mounts,
             "tool_count": len(tool_names)},
            status_code=200 if ok else 503)


def main() -> None:
    import asyncio
    host = asyncio.run(build_entity_host())
    host.run(transport="http", host="127.0.0.1", port=int(os.environ.get("MCP_HOST_PORT", "8100")))


if __name__ == "__main__":
    main()
