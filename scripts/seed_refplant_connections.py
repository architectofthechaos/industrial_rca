"""Seed the 4 reference-plant connections as ``active`` in the MAR Postgres ``connections``
table (Sprint 4 WI1/WI3, demo gap D6).

For the live probe to route through the registry, ``rca_agents.host.router_from_connections``
reads ``repo.list_connections(status="active")``; if that's empty it falls back to the static
dev router. This script writes the same 4 connections the dev router hard-codes so the live
demo routes through the registry instead of the fallback.

Idempotent: ``PostgresRepository.upsert_connection`` does an ``on_conflict_do_update`` keyed on
``connection_id``, so re-running updates each row in place. The partial unique index
(one active connection per (plant_id, category)) only fires for a *different* connection_id in
the same active (plant, category) — re-running with these same ids never trips it.
"""
from __future__ import annotations

import asyncio

from rca_mar.config import make_engine, make_session_factory
from rca_mar.repository import ConnectionRow
from rca_mar.repository_pg import PostgresRepository

PLANT_ID = "refinery-gc"

# (connection_id, category, connector_type, base_url, display_name) — ids/categories/types/
# base_urls mirror rca_agents.host._static_dev_router exactly.
CONNECTIONS = [
    (
        f"{PLANT_ID}.historian.pi-main",
        "historian",
        "pi_historian",
        "http://127.0.0.1:8001",
        "PI Historian (refinery-gc)",
    ),
    (
        f"{PLANT_ID}.operator_log.pi-event-frames",
        "operator_log",
        "pi_event_frames",
        "http://127.0.0.1:8001",
        "PI Event Frames operator log (refinery-gc)",
    ),
    (
        f"{PLANT_ID}.cmms.maximo-main",
        "cmms",
        "maximo",
        "http://127.0.0.1:8002",
        "Maximo CMMS (refinery-gc)",
    ),
    (
        f"{PLANT_ID}.document.sharepoint-main",
        "document",
        "sharepoint",
        "http://127.0.0.1:8004",
        "SharePoint documents (refinery-gc)",
    ),
]


async def main() -> None:
    repo = PostgresRepository(make_session_factory(make_engine()))
    for connection_id, category, connector_type, base_url, display_name in CONNECTIONS:
        row = ConnectionRow(
            connection_id=connection_id,
            plant_id=PLANT_ID,
            category=category,
            connector_type=connector_type,
            display_name=display_name,
            base_url=base_url,
            auth_config={},
            status="active",
            extra_config={},
        )
        await repo.upsert_connection(row)
        print(f"seeded {connection_id} (active)")


if __name__ == "__main__":
    asyncio.run(main())
