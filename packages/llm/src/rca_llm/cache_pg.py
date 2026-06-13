"""Postgres-backed ResponseCache (WI5) — cross-process determinism replay. Implements the
ResponseCache Protocol (get/put). Mirrors PostgresLlmAuditSink's DB conventions."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rca_mar.config import make_engine, make_session_factory
from rca_mar.models import ResponseCacheRow


class PostgresResponseCache:
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(ResponseCacheRow.payload).where(ResponseCacheRow.prompt_hash == key)
                )
            ).scalar_one_or_none()
            return dict(row) if row is not None else None

    async def put(self, key: str, value: dict[str, Any]) -> None:
        async with self._sf() as s, s.begin():
            stmt = pg_insert(ResponseCacheRow).values(prompt_hash=key, payload=value)
            await s.execute(
                stmt.on_conflict_do_nothing(index_elements=[ResponseCacheRow.prompt_hash])
            )


__all__ = ["PostgresResponseCache"]
