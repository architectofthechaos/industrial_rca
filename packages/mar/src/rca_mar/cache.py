"""Per-tenant resolution cache: bounded LRU with a TTL (SPEC-011 perf target)."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable
from uuid import UUID

Loader = Callable[[UUID, str, str], Awaitable[Any]]


class ResolutionCache:
    def __init__(self, *, ttl_seconds: float = 60.0, maxsize: int = 10_000,
                 now: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._now = now
        self._data: OrderedDict[tuple[UUID, str, str], tuple[float, Any]] = OrderedDict()

    async def get_or_load(self, tenant: UUID, source: str, external_id: str, loader: Loader) -> Any:
        key = (tenant, source, external_id)
        hit = self._data.get(key)
        if hit is not None and (self._now() - hit[0]) < self._ttl:
            self._data.move_to_end(key)
            return hit[1]
        value = await loader(tenant, source, external_id)
        self._data[key] = (self._now(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)
        return value

    def invalidate(self, tenant: UUID, source: str, external_id: str) -> None:
        self._data.pop((tenant, source, external_id), None)


__all__ = ["ResolutionCache"]
