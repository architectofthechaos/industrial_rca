"""LLM-call audit sink (Sprint 3 WI1) — writes the ``llm_calls`` row for every call.

Every ``LLMClient.complete`` records one ``LlmCallRecord`` (provenance, token counts,
prompt_hash, probe_run_id when applicable, request/response payloads). The in-memory sink
backs tests; ``PostgresLlmAuditSink`` (in rca_mar's models/migration) writes the real table.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class LlmCallRecord(BaseModel):
    llm_call_id: UUID
    correlation_id: str
    probe_run_id: UUID | None = None
    prompt_name: str
    prompt_version: str
    prompt_hash: str
    model: str
    model_version: str
    temperature: float
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool
    request_payload: dict = Field(default_factory=dict)
    response_payload: dict = Field(default_factory=dict)
    created_at: datetime


class AuditSink(Protocol):
    async def record(self, call: LlmCallRecord) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.calls: list[LlmCallRecord] = []

    async def record(self, call: LlmCallRecord) -> None:
        self.calls.append(call)

    def for_probe(self, probe_run_id: UUID) -> list[LlmCallRecord]:
        return [c for c in self.calls if c.probe_run_id == probe_run_id]


class NullAuditSink:
    async def record(self, call: LlmCallRecord) -> None:  # noqa: ARG002
        return None


__all__ = ["LlmCallRecord", "AuditSink", "InMemoryAuditSink", "NullAuditSink"]
