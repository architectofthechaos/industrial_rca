#!/usr/bin/env python
"""Single-process MCP host — mounts all six entity MCP servers into ONE FastMCP process.

Phase 1 ships one MCP server per canonical entity category (spec §7.1): asset, tag,
work_order, document, operator_log, kg. Rather than run six OS processes, this dev host
mounts each entity server (built by its `make_*_mcp` factory) into a single FastMCP
instance via `FastMCP.mount(sub)` and serves them on one HTTP port (:8100). Mounting with
NO prefix preserves each server's already-entity-vocabulary tool names verbatim
(`asset.get`, `tag.list_for_asset`, `work_order.list_for_asset`, ...), so the surface a
caller sees is identical to running the servers standalone.

Risk callout #5 (single-process multi-mount): co-locating the six servers trades process
isolation for operational simplicity. One crashing tool can take the whole host down, and
they share a Python GIL / event loop. Acceptable for Phase 1 dev + the onboarding pipeline;
splitting back into per-entity processes is a config change (each factory already stands
alone), not a rewrite. See docs/mcp/entity-topology.md.

Connection routing: the connector-backed servers (tag, work_order, document, operator_log)
resolve a request's (plant_id, category) to an active connection through a ConnectionRouter.
This dev default wires a StaticConnectionRouter with the reference-plant connections pointing
at the local simulators. The asset (MAR) and kg servers read their own stores directly.

This is a DEV CONVENIENCE script — it is NOT imported by tests. Run it with:

    uv run python scripts/run_mcp_host.py            # serve on http://127.0.0.1:8100/mcp
    uv run python scripts/run_mcp_host.py --check     # build + list tools, then exit (no serve)

Env overrides (all optional; defaults target the local refplant simulators):
    MCP_HOST_PORT          host port (default 8100)
    HISTORIAN_SIM_URL      PI historian + event frames sim (default http://127.0.0.1:8001)
    CMMS_SIM_URL           Maximo sim                       (default http://127.0.0.1:8002)
    DOCUMENT_SIM_URL       SharePoint/docs sim              (default http://127.0.0.1:8004)
    KG_URI / KG_USERNAME / KG_PASSWORD   Neo4j (see rca_kg.config); the kg driver connects
                                          lazily on first tool call, so the host starts even
                                          if Neo4j is down.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from uuid import UUID

from fastmcp import Client, FastMCP
from rca_connector_sdk import (
    CanonicalSlugAssetGateway,
    ConnectionInfo,
    StaticConnectionRouter,
)
from rca_connector_documents.server import make_document_mcp
from rca_connector_maximo.server import make_work_order_mcp
from rca_connector_pi.server import make_operator_log_mcp, make_tag_mcp
from rca_kg.queries import Neo4jGateway
from rca_kg.server import make_kg_mcp
from rca_mar.repository import InMemoryRepository
from rca_mar.seed import seed_from_register
from rca_mar.server import make_mar_mcp

# Reference-plant identity (matches the MAR seed + simulator fixtures).
PLANT_ID = "refinery-gc"
TENANT_ID = UUID("0190d3c9-0000-7000-8000-0000000000ff")
HOST_PORT = int(os.environ.get("MCP_HOST_PORT", "8100"))

# Local simulator endpoints, by entity category (spec §8.3 coverage).
HISTORIAN_SIM_URL = os.environ.get("HISTORIAN_SIM_URL", "http://127.0.0.1:8001")
CMMS_SIM_URL = os.environ.get("CMMS_SIM_URL", "http://127.0.0.1:8002")
DOCUMENT_SIM_URL = os.environ.get("DOCUMENT_SIM_URL", "http://127.0.0.1:8004")

_REGISTER = (
    Path(__file__).resolve().parents[1]
    / "packages" / "mar" / "seed_data" / "refplant_assets.yaml"
)


def _dev_router() -> StaticConnectionRouter:
    """One active connection per category for the reference plant (Phase 1: one source/category).

    operator_log shares the historian sim (PI event frames live alongside the PI historian);
    they are distinct categories so each still resolves to its own ConnectionInfo.
    """
    return StaticConnectionRouter([
        ConnectionInfo(
            connection_id=f"{PLANT_ID}.historian.pi-main", plant_id=PLANT_ID,
            category="historian", connector_type="pi_historian", base_url=HISTORIAN_SIM_URL,
        ),
        ConnectionInfo(
            connection_id=f"{PLANT_ID}.operator_log.pi-event-frames", plant_id=PLANT_ID,
            category="operator_log", connector_type="pi_event_frames",
            base_url=HISTORIAN_SIM_URL,
        ),
        ConnectionInfo(
            connection_id=f"{PLANT_ID}.cmms.maximo-main", plant_id=PLANT_ID,
            category="cmms", connector_type="maximo", base_url=CMMS_SIM_URL,
        ),
        ConnectionInfo(
            connection_id=f"{PLANT_ID}.document.sharepoint-main", plant_id=PLANT_ID,
            category="document", connector_type="sharepoint", base_url=DOCUMENT_SIM_URL,
        ),
    ])


async def build_host() -> FastMCP:
    """Construct the six entity MCP servers and mount them into one FastMCP host.

    The asset (MAR) server is seeded from the product-owned reference register into an
    in-memory repository. Connector-backed servers share the dev router + a slug gateway
    (canonical_id -> historian tag); CMMS/document handles that the slug can't derive will
    surface a clean not_found until a MAR-backed gateway is wired (Track 1).
    """
    router = _dev_router()
    gateway = CanonicalSlugAssetGateway()

    repo = InMemoryRepository()
    await seed_from_register(repo, _REGISTER)

    host = FastMCP("entity-mcp-host")
    host.mount(make_mar_mcp(repo=repo, tenant_id=TENANT_ID))
    host.mount(make_kg_mcp(gateway=Neo4jGateway()))
    host.mount(make_tag_mcp(router=router, assets=gateway,
                            default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_operator_log_mcp(router=router, assets=gateway,
                                     default_base_url=HISTORIAN_SIM_URL))
    host.mount(make_work_order_mcp(router=router, assets=gateway,
                                   default_base_url=CMMS_SIM_URL))
    host.mount(make_document_mcp(router=router, assets=gateway,
                                 default_base_url=DOCUMENT_SIM_URL))
    return host


async def _check() -> None:
    """Build the host and print its mounted tool surface, then exit (no network listen)."""
    host = await build_host()
    async with Client(host) as client:
        names = sorted(t.name for t in await client.list_tools())
    print(f"entity-mcp-host: {len(names)} tools mounted")
    for name in names:
        print(f"  {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="build the host + list tools, then exit (no HTTP listen)")
    parser.add_argument("--port", type=int, default=HOST_PORT,
                        help=f"HTTP port to serve on (default {HOST_PORT})")
    args = parser.parse_args()

    if args.check:
        asyncio.run(_check())
        return

    host = asyncio.run(build_host())
    host.run(transport="http", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
