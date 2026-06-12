"""Connection routing — pick the configured connection that serves a (plant, category).

A connector instance can be wired to several source connections (e.g. two PI historians for
one plant). The router resolves which one to use for a request: an explicit connection_id wins;
otherwise the single active connection for the (plant_id, category) pair is used. Zero or more
than one (without an explicit id) is an error — the caller must disambiguate.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .errors import ConnectorError


@dataclass(frozen=True)
class ConnectionInfo:
    connection_id: str
    plant_id: str
    category: str
    connector_type: str
    base_url: str
    extra_config: dict = field(default_factory=dict)


class NoActiveConnection(ConnectorError):
    """No connection (or no unambiguous connection) matched the requested scope.

    Maps to ``source_unavailable`` (not ``internal_error``): a missing/ambiguous
    connection is a configuration state the caller can fix, not a connector bug.
    Not retryable — retrying the same call won't help until the config changes.
    """

    code = "source_unavailable"
    retryable = False


@runtime_checkable
class ConnectionRouter(Protocol):
    async def active(
        self, plant_id: str, category: str, connection_id: str | None = None
    ) -> ConnectionInfo: ...


class StaticConnectionRouter:
    """Dict-backed router for dev/tests; stands in for the connections registry (Track 1)."""

    def __init__(self, connections: list[ConnectionInfo]) -> None:
        self._connections = list(connections)
        self._by_id = {c.connection_id: c for c in self._connections}

    async def active(
        self, plant_id: str, category: str, connection_id: str | None = None
    ) -> ConnectionInfo:
        if connection_id is not None:
            conn = self._by_id.get(connection_id)
            if conn is None:
                raise NoActiveConnection(f"no connection with id {connection_id!r}")
            if conn.plant_id != plant_id or conn.category != category:
                raise NoActiveConnection(
                    f"connection {connection_id!r} is not for "
                    f"(plant={plant_id!r}, category={category!r})"
                )
            return conn

        matches = [
            c for c in self._connections
            if c.plant_id == plant_id and c.category == category
        ]
        if not matches:
            raise NoActiveConnection(
                f"no active connection for (plant={plant_id!r}, category={category!r})"
            )
        if len(matches) > 1:
            ids = ", ".join(sorted(c.connection_id for c in matches))
            raise NoActiveConnection(
                f"ambiguous: {len(matches)} connections for "
                f"(plant={plant_id!r}, category={category!r}): {ids}; pass connection_id"
            )
        return matches[0]


# async (plant_id, category) -> the currently-active ConnectionInfos for that scope.
ConnectionsProvider = Callable[[str, str], Awaitable[list[ConnectionInfo]]]


class RegistryConnectionRouter:
    """ConnectionRouter that resolves from a LIVE registry **per request** (D10).

    ``provider(plant_id, category)`` returns the currently-active connections for that scope
    (the composition root wires it to ``connections_api``/MAR ``list_connections(status='active')``
    — connector_sdk stays free of any registry dependency). The resolution rules — explicit
    ``connection_id`` wins / single active used / zero -> ``NoActiveConnection`` / 2+ ambiguous ->
    ``NoActiveConnection`` — are IDENTICAL to ``StaticConnectionRouter`` (delegated verbatim).

    Because the active set is fetched per call, a connect/disconnect in the registry takes effect
    on the next tool call — no worker restart (this is the whole point of D10, vs the boot-time
    static snapshot). ``ttl_seconds`` (default 0 = per-request) bounds registry load when a probe
    issues many calls in quick succession; the reroute latency is then at most the TTL.
    """

    def __init__(self, provider: ConnectionsProvider, *, ttl_seconds: float = 0.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._provider = provider
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, list[ConnectionInfo]]] = {}

    async def active(
        self, plant_id: str, category: str, connection_id: str | None = None
    ) -> ConnectionInfo:
        infos = await self._fetch(plant_id, category)
        # delegate to the static rules so resolution behavior is provably identical
        return await StaticConnectionRouter(infos).active(plant_id, category, connection_id)

    async def _fetch(self, plant_id: str, category: str) -> list[ConnectionInfo]:
        key = (plant_id, category)
        if self._ttl > 0:
            cached = self._cache.get(key)
            if cached is not None and cached[0] > self._clock():
                return cached[1]
        infos = list(await self._provider(plant_id, category))
        if self._ttl > 0:
            self._cache[key] = (self._clock() + self._ttl, infos)
        return infos


__all__ = [
    "ConnectionInfo", "NoActiveConnection", "ConnectionRouter", "StaticConnectionRouter",
    "RegistryConnectionRouter", "ConnectionsProvider",
]
