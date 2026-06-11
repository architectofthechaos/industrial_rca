"""Content-addressed response cache (Sprint 3 WI1).

Keyed by ``prompt_hash`` (SHA-256 of the rendered prompt). On a hit with
``replay_from_cache=True`` the client returns the cached response and makes NO upstream
call — the basis for byte-identical, hermetic, network-free probe replays (cross-cutting
acceptance #15/#18). The in-memory cache backs tests; a Postgres-backed cache can replace
it without touching the client.
"""
from __future__ import annotations

import hashlib
from typing import Any, Protocol


def prompt_hash(rendered_prompt: str) -> str:
    return hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()


class ResponseCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any]) -> None: ...


class InMemoryResponseCache:
    def __init__(self, seed: dict[str, dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = dict(seed or {})

    async def get(self, key: str) -> dict[str, Any] | None:
        value = self._store.get(key)
        return dict(value) if value is not None else None

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = dict(value)

    def __len__(self) -> int:
        return len(self._store)


__all__ = ["prompt_hash", "ResponseCache", "InMemoryResponseCache"]
