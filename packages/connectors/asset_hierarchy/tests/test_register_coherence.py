"""Cross-source coherence: the re-keyed seed register agrees with what the crawler finds.

Hermetic (fake_af + InMemoryRepository), but pinned to the REAL committed register:
the fake AF replicates the simulator's deterministic WebId scheme, so the WebIds the
crawler discovers here must equal the WebIds the one-time online re-key
(packages/mar/seed_data/scripts/rekey_pi_af_webids.py) wrote into refplant_assets.yaml.
A mismatch means the register, the sim hierarchy, or the WebId scheme drifted —
investigate, don't fudge.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import yaml
from fake_af import DB_NAME, fake_client, make_fake_af_app
from rca_mar.repository import InMemoryRepository
from rca_mar.resolution import resolve_asset
from rca_mar.seed import seed_from_register

from rca_connector_asset_hierarchy.crawler import crawl
from rca_connector_asset_hierarchy.models import CrawlResult

PLANT = "refinery-gc"
REGISTER = Path(__file__).resolve().parents[3] / "mar" / "seed_data" / "refplant_assets.yaml"
REGISTER_DOC = yaml.safe_load(REGISTER.read_text())
TENANT = UUID(str(REGISTER_DOC["tenant_id"]))
PI_AF_BY_TAG = {a["tag"]: a["external_ids"]["pi_af"] for a in REGISTER_DOC["assets"]}


async def _seeded_repo_and_crawl() -> tuple[InMemoryRepository, CrawlResult]:
    repo = InMemoryRepository()
    await seed_from_register(repo, REGISTER)
    async with fake_client(make_fake_af_app()) as client:
        result = await crawl(client, database_name=DB_NAME, plant_id=PLANT)
    return repo, result


async def test_crawler_discovery_matches_rekeyed_register_for_both_seeded_assets():
    repo, result = await _seeded_repo_and_crawl()
    discovered = {a.name: a for a in result.assets}
    for tag in ("P-101A", "P-103A"):
        asset = discovered[tag]
        register_pi_af = PI_AF_BY_TAG[tag]
        assert asset.vendor_id == register_pi_af["external_id"]       # WebId-keyed register
        assert asset.vendor_path == register_pi_af["vendor_path"]
        seeded = await repo.find_asset_by_tag(TENANT, tag)
        assert seeded is not None
        assert asset.proposed_canonical_id == seeded.canonical_id     # same dual-key identity


async def test_resolve_by_maximo_id_lands_on_the_asset_the_crawler_proposes():
    # cross-source acceptance: asset.resolve via the Maximo external_id binds the SAME
    # asset the crawler proposes for P-101A
    repo, result = await _seeded_repo_and_crawl()
    resolution = await resolve_asset(repo, "CRDU-P101A", "maximo", TENANT)
    assert resolution.status == "resolved" and resolution.asset_id is not None
    resolved = await repo.get_asset(TENANT, resolution.asset_id)
    proposed = next(a for a in result.assets if a.name == "P-101A")
    assert resolved is not None
    assert resolved.canonical_id == proposed.proposed_canonical_id


async def test_rekeyed_register_seeds_webid_keyed_pi_af_lookups():
    repo, result = await _seeded_repo_and_crawl()
    web_id = next(a.vendor_id for a in result.assets if a.name == "P-101A")
    alias = await repo.find_active_alias(TENANT, "pi_af", web_id, valid_at=None)
    assert alias is not None
    assert alias.vendor_path == PI_AF_BY_TAG["P-101A"]["vendor_path"]
    assert alias.source_system_type == "asset_hierarchy"
