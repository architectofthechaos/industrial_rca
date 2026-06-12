"""RegistryConnectionRouter — per-request resolution from a live registry (Sprint 5 WI4 / D10).

Covers the four resolution rules (explicit / single / none / ambiguous) and the headline:
connect/disconnect in the registry takes effect on the NEXT call with no router reconstruction
(vs the boot-time static snapshot).
"""
from __future__ import annotations

import pytest

from rca_connector_sdk.routing import (
    ConnectionInfo,
    NoActiveConnection,
    RegistryConnectionRouter,
)

PLANT = "refinery-gc"


def _conn(cid: str, category: str = "historian", base: str = "http://sim:8001") -> ConnectionInfo:
    return ConnectionInfo(connection_id=cid, plant_id=PLANT, category=category,
                          connector_type="pi_historian", base_url=base)


def _provider_returning(*infos: ConnectionInfo):
    async def provider(plant_id: str, category: str) -> list[ConnectionInfo]:
        return [c for c in infos if c.plant_id == plant_id and c.category == category]
    return provider


@pytest.mark.asyncio
async def test_single_active_used():
    r = RegistryConnectionRouter(_provider_returning(_conn("pi-main")))
    conn = await r.active(PLANT, "historian")
    assert conn.connection_id == "pi-main"


@pytest.mark.asyncio
async def test_explicit_connection_id_wins():
    r = RegistryConnectionRouter(_provider_returning(_conn("pi-a"), _conn("pi-b")))
    conn = await r.active(PLANT, "historian", connection_id="pi-b")
    assert conn.connection_id == "pi-b"


@pytest.mark.asyncio
async def test_zero_active_raises():
    r = RegistryConnectionRouter(_provider_returning())
    with pytest.raises(NoActiveConnection):
        await r.active(PLANT, "historian")


@pytest.mark.asyncio
async def test_ambiguous_without_explicit_id_raises():
    r = RegistryConnectionRouter(_provider_returning(_conn("pi-a"), _conn("pi-b")))
    with pytest.raises(NoActiveConnection):
        await r.active(PLANT, "historian")


@pytest.mark.asyncio
async def test_disable_reroutes_on_next_call_without_restart():
    """D10 headline: mutate the registry's active set between calls; the SAME router instance
    reflects it on the next call (per-request resolution), no reconstruction/restart."""
    active = {"set": [_conn("pi-main", base="http://pi-main:8001")]}

    async def provider(plant_id, category):
        return [c for c in active["set"] if c.plant_id == plant_id and c.category == category]

    r = RegistryConnectionRouter(provider)   # ttl=0 -> per request
    assert (await r.active(PLANT, "historian")).base_url == "http://pi-main:8001"

    # operator disables pi-main and brings up pi-backup at a different base_url
    active["set"] = [_conn("pi-backup", base="http://pi-backup:8001")]
    assert (await r.active(PLANT, "historian")).base_url == "http://pi-backup:8001"

    # disable everything -> next call raises (the static snapshot could never do this)
    active["set"] = []
    with pytest.raises(NoActiveConnection):
        await r.active(PLANT, "historian")


@pytest.mark.asyncio
async def test_ttl_cache_bounds_provider_calls():
    calls = {"n": 0}
    t = {"now": 0.0}

    async def provider(plant_id, category):
        calls["n"] += 1
        return [_conn("pi-main")]

    r = RegistryConnectionRouter(provider, ttl_seconds=5.0, clock=lambda: t["now"])
    await r.active(PLANT, "historian")
    await r.active(PLANT, "historian")        # within TTL -> served from cache
    assert calls["n"] == 1
    t["now"] = 6.0                            # TTL expired -> re-query
    await r.active(PLANT, "historian")
    assert calls["n"] == 2
