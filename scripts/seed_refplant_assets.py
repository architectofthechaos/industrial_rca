"""Seed the reference-plant MAR assets into the LIVE Postgres MAR (Sprint 4 WI1/WI3).

``stack:up`` seeds the KG hierarchy and the refplant connections, but nothing seeded the MAR
``assets`` table — so the live probe's ``asset.search`` / ``asset.get`` returned empty and the
probe dead-ended in planning. This script loads the product-owned authoritative register
(``packages/mar/seed_data/refplant_assets.yaml``) into Postgres via the same code path the dev
MCP host uses (``rca_mar.seed.seed_from_register``).

NOTE — connections side effect: ``seed_from_register`` ALSO upserts the register's *default*
connections (one per source referenced in any asset's ``external_ids``: ``maximo``/``sap_pm``/
``pi_af``/``uns``), because each asset alias FKs its owning connection. Two of those land
``active`` in categories the probe also owns (``cmms`` -> ``maximo-default``, ``historian`` ->
``uns-default``). ``scripts/seed_refplant_connections.py`` reconciles that by demoting any
conflicting active before installing the probe's four — so this script MUST run BEFORE it
(``stack:up`` orders them that way).

Idempotent: ``upsert_asset`` / ``upsert_connection`` use ``on_conflict_do_update`` keyed on the
PK, and ``upsert_alias`` closes the prior active row then inserts the new one (no unique-index
violation), so re-running this script never errors.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from rca_mar.config import make_engine, make_session_factory
from rca_mar.repository_pg import PostgresRepository
from rca_mar.seed import seed_from_register

PLANT_ID = "refinery-gc"
TENANT_ID = UUID("0190d3c9-0000-7000-8000-0000000000ff")
REGISTER = (
    Path(__file__).resolve().parents[1]
    / "packages" / "mar" / "seed_data" / "refplant_assets.yaml"
)


async def main() -> None:
    repo = PostgresRepository(make_session_factory(make_engine()))
    await seed_from_register(repo, REGISTER)

    # Summarise what landed: count of registered assets + spotlight P-101A (the live probe's
    # scenario asset) so the operator can confirm its KG class binding at a glance.
    assets = await repo.search_assets(TENANT_ID, limit=1000)
    print(f"seeded {len(assets)} asset(s) from {REGISTER.name} into MAR ({PLANT_ID})")
    for a in sorted(assets, key=lambda x: x.canonical_id):
        print(f"  {a.tag:8} {a.canonical_id:40} iso14224_class_kg={a.iso14224_class_kg}")

    p101a = await repo.find_asset_by_tag(TENANT_ID, "P-101A")
    if p101a is None:
        raise SystemExit("ERROR: P-101A not found after seeding")
    print(
        f"P-101A registered: canonical_id={p101a.canonical_id} "
        f"iso14224_class_kg={p101a.iso14224_class_kg}"
    )


if __name__ == "__main__":
    asyncio.run(main())
