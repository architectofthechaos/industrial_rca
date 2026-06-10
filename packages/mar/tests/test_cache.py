from uuid import uuid4

from rca_mar.cache import ResolutionCache

TENANT = uuid4()


async def test_cache_hit_avoids_recompute():
    calls = {"n": 0}

    async def loader(tenant, source, external_id):
        calls["n"] += 1
        return f"asset-for-{external_id}"

    clock = {"t": 1000.0}
    cache = ResolutionCache(ttl_seconds=60, now=lambda: clock["t"])
    assert await cache.get_or_load(TENANT, "maximo", "X", loader) == "asset-for-X"
    assert await cache.get_or_load(TENANT, "maximo", "X", loader) == "asset-for-X"
    assert calls["n"] == 1


async def test_cache_expires_after_ttl():
    calls = {"n": 0}

    async def loader(tenant, source, external_id):
        calls["n"] += 1
        return external_id

    clock = {"t": 0.0}
    cache = ResolutionCache(ttl_seconds=60, now=lambda: clock["t"])
    await cache.get_or_load(TENANT, "maximo", "X", loader)
    clock["t"] = 61.0
    await cache.get_or_load(TENANT, "maximo", "X", loader)
    assert calls["n"] == 2
