"""Resolution Queue REST endpoints (Sprint 2b §4.2, §4.3 acceptance).

Hermetic: a FastAPI TestClient over create_app(repo=InMemoryRepository()) seeded with
pending_review bindings via repo.upsert_alias. No DB, no sim.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import TypeVar
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from rca_contracts import AssetDescriptor

from rca_connections_api import create_app
from rca_connections_api.app import DEFAULT_TENANT_ID
from rca_mar.repository import AliasRow, ConnectionRow, InMemoryRepository

TENANT = DEFAULT_TENANT_ID
CONN = "refinery-gc.cmms.maximo-default"

_T = TypeVar("_T")


def _run(coro: Awaitable[_T]) -> _T:
    """Drive an async repo helper from a sync test (TestClient is sync). The endpoints run on
    their own loop inside TestClient; this loop is only used for direct repo seeding/reads."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _asset(asset_id, tag, plant_id="refinery-gc") -> AssetDescriptor:
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=f"asset:{plant_id}:unit-101:{tag.lower()}",
        tenant_id=TENANT, plant_id=plant_id,
        iso14224_class="pump.centrifugal", iso14224_level=6, tag=tag,
        service=None, criticality="A", manufacturer=None, model=None,
        serial_number=None, commissioned_at=None, decommissioned_at=None,
        location_description=None, description=None)


def _conn(connection_id=CONN, plant_id="refinery-gc") -> ConnectionRow:
    return ConnectionRow(
        connection_id=connection_id, plant_id=plant_id, category="cmms",
        connector_type="maximo", display_name="maximo", base_url="http://localhost:8002",
        auth_config={"type": "none", "secret_ref": None}, status="active")


def _pending(asset_id, external_id="CRDU-P101A", connection_id=CONN, candidates=None) -> AliasRow:
    return AliasRow(
        asset_id=asset_id, tenant_id=TENANT, connection_id=connection_id,
        external_id=external_id, valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        valid_to=None, mapping_source="cross_walk", confidence=0.7, is_primary=False,
        resolution_status="pending_review", resolved_by="system",
        candidate_alternatives=candidates)


async def _seed(repo, *, with_alt=False):
    pump = uuid4()
    await repo.upsert_asset(_asset(pump, "P-101A"))
    await repo.upsert_connection(_conn())
    candidates = [{"canonical_id": "asset:refinery-gc:unit-101:p-101a", "confidence": 0.7,
                   "method": "cross_walk"}]
    alt = None
    if with_alt:
        alt = uuid4()
        await repo.upsert_asset(_asset(alt, "P-101B"))
        candidates.append({"canonical_id": "asset:refinery-gc:unit-101:p-101b",
                           "confidence": 0.6, "method": "cross_walk"})
    await repo.upsert_alias(_pending(pump, candidates=candidates))
    return pump, alt


def _client():
    repo = InMemoryRepository()
    return TestClient(create_app(repo=repo)), repo


async def _alias_id(repo) -> str:
    rows = await repo.list_pending_bindings(TENANT)
    return str(rows[0].alias_id)


# -- list ----------------------------------------------------------------

def test_get_lists_pending_with_candidate_alternatives():
    client, repo = _client()
    pump, _ = _run(_seed(repo, with_alt=True))

    resp = client.get("/resolution_queue")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["asset_id"] == str(pump)
    assert item["resolution_status"] == "pending_review"
    assert item["connection_id"] == CONN
    assert item["canonical_id"] == "asset:refinery-gc:unit-101:p-101a"
    assert len(item["candidate_alternatives"]) == 2


def test_get_filters_by_plant_and_connection():
    client, repo = _client()

    async def seed():
        a1, a2 = uuid4(), uuid4()
        await repo.upsert_asset(_asset(a1, "P-101A", plant_id="refinery-gc"))
        await repo.upsert_asset(_asset(a2, "P-201A", plant_id="plant-b"))
        await repo.upsert_connection(_conn())
        await repo.upsert_connection(_conn("plant-b.cmms.maximo-default", plant_id="plant-b"))
        await repo.upsert_alias(_pending(a1, external_id="E1"))
        await repo.upsert_alias(_pending(a2, external_id="E2",
                                         connection_id="plant-b.cmms.maximo-default"))
    _run(seed())

    assert len(client.get("/resolution_queue").json()) == 2
    assert len(client.get("/resolution_queue", params={"connection_id": CONN}).json()) == 1
    assert len(client.get("/resolution_queue", params={"plant_id": "plant-b"}).json()) == 1


# -- validate ------------------------------------------------------------

def test_validate_transitions_to_human_validated_and_persists():
    client, repo = _client()
    _run(_seed(repo))
    alias_id = _run(_alias_id(repo))

    resp = client.post(f"/resolution_queue/{alias_id}/validate",
                       json={"validated_by": "jane"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolution_status"] == "human_validated"
    assert resp.json()["validated_by"] == "jane"

    # persisted: it is no longer in the pending queue
    assert client.get("/resolution_queue").json() == []
    stored = _run(repo.get_alias(UUID(alias_id)))
    assert stored.resolution_status == "human_validated" and stored.validated_by == "jane"


def test_validate_with_matching_canonical_is_a_plain_validate():
    client, repo = _client()
    _run(_seed(repo))
    alias_id = _run(_alias_id(repo))
    resp = client.post(f"/resolution_queue/{alias_id}/validate",
                       json={"validated_by": "jane",
                             "accepted_canonical_id": "asset:refinery-gc:unit-101:p-101a"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolution_status"] == "human_validated"
    # same alias_id was validated in place (no new binding minted)
    assert resp.json()["alias_id"] == alias_id


def test_validate_with_different_canonical_supersedes_and_creates_new_binding():
    client, repo = _client()
    pump, alt = _run(_seed(repo, with_alt=True))
    alias_id = _run(_alias_id(repo))

    resp = client.post(f"/resolution_queue/{alias_id}/validate",
                       json={"validated_by": "jane",
                             "accepted_canonical_id": "asset:refinery-gc:unit-101:p-101b"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # a NEW binding to the alternative asset, human_validated + manual
    assert body["asset_id"] == str(alt)
    assert body["canonical_id"] == "asset:refinery-gc:unit-101:p-101b"
    assert body["resolution_status"] == "human_validated"
    assert body["mapping_source"] == "manual"
    assert body["validated_by"] == "jane"
    assert body["alias_id"] != alias_id

    # the original binding is superseded + closed
    old = _run(repo.get_alias(UUID(alias_id)))
    assert old.resolution_status == "superseded" and old.valid_to is not None
    # the queue is now empty (new row is human_validated, old is superseded)
    assert client.get("/resolution_queue").json() == []


def test_validate_with_canonical_not_a_candidate_422():
    client, repo = _client()
    _run(_seed(repo, with_alt=True))
    alias_id = _run(_alias_id(repo))
    resp = client.post(f"/resolution_queue/{alias_id}/validate",
                       json={"validated_by": "jane",
                             "accepted_canonical_id": "asset:refinery-gc:unit-101:not-a-candidate"})
    assert resp.status_code == 422, resp.text


# -- reject --------------------------------------------------------------

def test_reject_closes_valid_to_and_sets_status():
    client, repo = _client()
    _run(_seed(repo))
    alias_id = _run(_alias_id(repo))
    resp = client.post(f"/resolution_queue/{alias_id}/reject",
                       json={"rejected_by": "jane", "reason": "wrong asset"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolution_status"] == "rejected"
    assert resp.json()["valid_to"] is not None
    stored = _run(repo.get_alias(UUID(alias_id)))
    assert stored.resolution_status == "rejected"
    assert "rejected: wrong asset" in stored.notes


# -- stats ---------------------------------------------------------------

def test_stats_aggregates_by_connection_and_status():
    client, repo = _client()

    async def seed():
        a1, a2 = uuid4(), uuid4()
        await repo.upsert_asset(_asset(a1, "P-101A"))
        await repo.upsert_asset(_asset(a2, "P-102A"))
        await repo.upsert_connection(_conn())
        await repo.upsert_alias(_pending(a1, external_id="E1"))
        await repo.upsert_alias(_pending(a2, external_id="E2"))
        rows = await repo.list_pending_bindings(TENANT)
        await repo.validate_binding(rows[0].alias_id, "jane")
    _run(seed())

    resp = client.get("/resolution_queue/stats")
    assert resp.status_code == 200, resp.text
    by_status = {r["resolution_status"]: r["count"] for r in resp.json()
                 if r["connection_id"] == CONN}
    assert by_status == {"pending_review": 1, "human_validated": 1}


# -- errors --------------------------------------------------------------

def test_validate_unknown_alias_404():
    client, _ = _client()
    resp = client.post(f"/resolution_queue/{uuid4()}/validate", json={"validated_by": "jane"})
    assert resp.status_code == 404


def test_validate_after_reject_409_invalid_transition():
    client, repo = _client()
    _run(_seed(repo))
    alias_id = _run(_alias_id(repo))
    assert client.post(f"/resolution_queue/{alias_id}/reject",
                       json={"rejected_by": "jane", "reason": "bad"}).status_code == 200
    resp = client.post(f"/resolution_queue/{alias_id}/validate", json={"validated_by": "jane"})
    assert resp.status_code == 409, resp.text


# -- §4.3 acceptance: seed pending bindings -> GET returns them -----------

def test_seed_driven_acceptance_get_returns_seeded_pending():
    client, repo = _client()

    async def seed():
        await repo.upsert_connection(_conn())
        for i in range(3):
            aid = uuid4()
            await repo.upsert_asset(_asset(aid, f"P-10{i}A"))
            await repo.upsert_alias(_pending(
                aid, external_id=f"EXT-{i}",
                candidates=[{"canonical_id": f"asset:refinery-gc:unit-101:p-10{i}a",
                             "confidence": 0.7, "method": "cross_walk"}]))
    _run(seed())

    resp = client.get("/resolution_queue")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 3
    assert all(d["resolution_status"] == "pending_review" for d in data)
    assert all(d["candidate_alternatives"] for d in data)
