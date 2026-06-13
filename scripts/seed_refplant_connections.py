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

Reconciliation (Sprint 4 WI3, demo gap D6): ``scripts/seed_refplant_assets.py`` runs first in
``stack:up`` and, as a side effect of seeding asset aliases, upserts the register's *default*
connections — two of which land ``active`` in categories this script also owns
(``cmms`` -> ``refinery-gc.cmms.maximo-default``, ``historian`` -> ``refinery-gc.historian.uns-default``).
Those would collide with this script's ``maximo-main`` / ``pi-main`` under the partial unique
index. So BEFORE upserting each of the four probe connections as ``active``, we DEMOTE any
*other* active connection in the same (plant, category) to ``disabled``. This makes the four
probe connections the sole actives for historian / operator_log / cmms / document, and keeps the
script idempotent (on re-run there is nothing left to demote).

After demotion, active aliases on the demoted connection are REBOUND onto the new active
connection (``connection_rebind``). ``MarAssetGateway`` resolves CMMS handles only against the
active connection — without this step, work-order gather fails even though the simulator is up.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from rca_mar.config import make_engine, make_session_factory
from rca_mar.repository import AliasRow, ConnectionRow
from rca_mar.repository_pg import PostgresRepository

PLANT_ID = "refinery-gc"
TENANT_ID = UUID("0190d3c9-0000-7000-8000-0000000000ff")

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


async def _demote_conflicting_actives(
    repo: PostgresRepository, *, category: str, keep_connection_id: str
) -> list[str]:
    """Disable any OTHER active connection in (PLANT_ID, category) so the probe's connection can
    take the single active slot. No-op when nothing else is active (idempotent on re-run).

    Returns the connection_ids that were demoted so callers can rebind their aliases onto the
    new active connection (G28/D13: MarAssetGateway resolves handles only on the active conn).
    """
    demoted: list[str] = []
    actives = await repo.list_connections(
        plant_id=PLANT_ID, category=category, status="active")
    for existing in actives:
        if existing.connection_id == keep_connection_id:
            continue
        await repo.upsert_connection(replace(existing, status="disabled"))
        demoted.append(existing.connection_id)
        print(f"demoted {existing.connection_id} ({category}) active -> disabled")
    return demoted


async def _rebind_aliases(
    repo: PostgresRepository, *, from_connection_id: str, to_connection_id: str
) -> None:
    """Copy active aliases from a demoted connection onto the new active one.

    Idempotent: upsert_alias closes any prior row for (tenant, to_connection, external_id)
    before inserting. Safe to re-run after stack:up.
    """
    now = datetime.now(timezone.utc)
    for alias in await repo.list_active_aliases_for_connection(TENANT_ID, from_connection_id):
        await repo.upsert_alias(AliasRow(
            asset_id=alias.asset_id, tenant_id=alias.tenant_id,
            connection_id=to_connection_id, external_id=alias.external_id,
            valid_from=now, valid_to=None,
            mapping_source="connection_rebind", confidence=alias.confidence,
            is_primary=alias.is_primary, resolution_status=alias.resolution_status,
            candidate_alternatives=alias.candidate_alternatives,
            resolved_by=alias.resolved_by or "system",
            vendor_path=alias.vendor_path, vendor_metadata=alias.vendor_metadata,
            confirmed_by=alias.confirmed_by,
            notes=f"rebound {from_connection_id} -> {to_connection_id}",
        ))
        print(f"rebound alias {alias.external_id!r} {from_connection_id} -> {to_connection_id}")


async def main() -> None:
    repo = PostgresRepository(make_session_factory(make_engine()))
    for connection_id, category, connector_type, base_url, display_name in CONNECTIONS:
        # Clear the (plant, category) active slot first so the partial unique index
        # uq_connection_active_category never trips when we upsert this row as active —
        # whether the colliding active came from the register defaults or a prior run.
        demoted = await _demote_conflicting_actives(
            repo, category=category, keep_connection_id=connection_id)
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
        for old_id in demoted:
            await _rebind_aliases(
                repo, from_connection_id=old_id, to_connection_id=connection_id)


if __name__ == "__main__":
    asyncio.run(main())
