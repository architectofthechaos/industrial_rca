"""Composition root: mount MAR + KG(+asset_graph) + connector MCP servers into one FastMCP.

This is the ONLY agents-package module allowed to import connector/MAR/KG servers (it is the
entrypoint, not agent logic — §8 scope note). The worker builds the host, wraps it in a
fastmcp.Client, and hands the client to McpToolBox. Swapping in-process for HTTP is a Client
construction change here; nothing in the toolbox or agents changes.
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


def _static_dev_router() -> StaticConnectionRouter:
    """One active connection per category for the reference plant (Phase 1: one source/category).

    operator_log shares the historian sim (PI event frames live alongside the PI historian);
    they are distinct categories so each still resolves to its own ConnectionInfo. Mirrors
    scripts/run_mcp_host.py's dev router — the un-seeded fallback for router_from_connections.
    """
    return StaticConnectionRouter([
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
    ])


async def router_from_connections() -> StaticConnectionRouter:
    """D6: build the static router from connections_api active connections; fall back to the
    static dev router when the registry is empty/unreachable (un-seeded dev box)."""
    try:
        repo = PostgresRepository(make_session_factory(make_engine()))
        rows = await repo.list_connections(status="active")
        infos = [ConnectionInfo(connection_id=r.connection_id, plant_id=r.plant_id,
                                category=r.category, connector_type=r.connector_type,
                                base_url=r.base_url, extra_config=r.extra_config or {})
                 for r in rows]
        if infos:
            return StaticConnectionRouter(infos)
    except Exception:  # noqa: BLE001 — registry not reachable on a fresh dev box
        pass
    return _static_dev_router()


async def build_entity_host(*, router: StaticConnectionRouter | None = None,
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
    if asset_graph is None:
        asset_graph = Neo4jAssetGraph()
    host = FastMCP("entity-mcp-host")
    host.mount(make_mar_mcp(repo=mar_repo, tenant_id=TENANT_ID))
    host.mount(make_kg_mcp(gateway=Neo4jGateway(), asset_graph=asset_graph))
    host.mount(make_tag_mcp(router=router, assets=gateway, default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_operator_log_mcp(router=router, assets=gateway,
                                     default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_work_order_mcp(router=router, assets=gateway, default_base_url=CMMS_SIM_URL))
    host.mount(make_document_mcp(router=router, assets=gateway, default_base_url=DOCUMENT_SIM_URL))
    return host


def main() -> None:
    import asyncio
    host = asyncio.run(build_entity_host())
    host.run(transport="http", host="127.0.0.1", port=int(os.environ.get("MCP_HOST_PORT", "8100")))


if __name__ == "__main__":
    main()
