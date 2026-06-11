"""Connection routing — pick the configured connection that serves a (plant, category).

A connector instance can be wired to several source connections (e.g. two PI historians for
one plant). The router resolves which one to use for a request: an explicit connection_id wins;
otherwise the single active connection for the (plant_id, category) pair is used. Zero or more
than one (without an explicit id) is an error — the caller must disambiguate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ConnectionInfo:
    connection_id: str
    plant_id: str
    category: str
    connector_type: str
    base_url: str
    extra_config: dict = field(default_factory=dict)


class NoActiveConnection(Exception):
    """No connection (or no unambiguous connection) matched the requested scope."""


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


__all__ = [
    "ConnectionInfo", "NoActiveConnection", "ConnectionRouter", "StaticConnectionRouter",
]
