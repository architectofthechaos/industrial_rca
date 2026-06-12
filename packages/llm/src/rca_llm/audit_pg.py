"""Postgres audit sink for LLM calls (WI5). Table + ORM (rca_mar.models.LlmCall) + migration
(0005) already exist — this only inserts. Idempotent on llm_call_id (Temporal activity retry)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from rca_mar.config import make_engine, make_session_factory
from rca_mar.models import LlmCall

from .audit import AuditSink, LlmCallRecord


class PostgresLlmAuditSink(AuditSink):
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def record(self, call: LlmCallRecord) -> None:
        values = call.model_dump()
        async with self._sf() as s, s.begin():
            stmt = pg_insert(LlmCall).values(**values).on_conflict_do_nothing(
                index_elements=[LlmCall.llm_call_id])
            await s.execute(stmt)


__all__ = ["PostgresLlmAuditSink"]
