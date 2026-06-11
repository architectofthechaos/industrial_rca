"""LLM-call and token-budget contracts (Sprint 3 WI1/WI2).

`TokenUsage` and `TokenBudget` are intentionally **mutable** (not frozen): the LLM
client increments `*_used` in place as calls are made within a single agent leg, and
the workflow threads the remaining budget into the next leg. Everything else in the
contracts package is frozen; these two are the deliberate exception.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ._base import StrictModel


class _MutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenUsage(_MutableModel):
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, *, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def merged_with(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class TokenBudget(_MutableModel):
    """Per-probe token budget. `complete()` raises TokenBudgetExceeded before a call
    that would push usage past a limit; the workflow catches it and emits a partial
    result with coverage.llm_status='budget_exceeded'."""

    input_tokens_limit: int = 50000
    output_tokens_limit: int = 10000
    input_used: int = 0
    output_used: int = 0

    def would_exceed(self, *, input_tokens: int, output_tokens: int) -> bool:
        return (
            self.input_used + input_tokens > self.input_tokens_limit
            or self.output_used + output_tokens > self.output_tokens_limit
        )

    def charge(self, *, input_tokens: int, output_tokens: int) -> None:
        self.input_used += input_tokens
        self.output_used += output_tokens

    @property
    def input_remaining(self) -> int:
        return max(0, self.input_tokens_limit - self.input_used)

    @property
    def output_remaining(self) -> int:
        return max(0, self.output_tokens_limit - self.output_used)


class TokenBudgetExceeded(Exception):
    """Raised by LLMClient.complete when a call would exceed the probe budget.

    Workflow-friendly: carries the budget snapshot so the workflow can record it.
    """

    def __init__(self, message: str, *, budget: TokenBudget | None = None) -> None:
        super().__init__(message)
        self.budget = budget


class LLMResponse(StrictModel):
    content: str
    structured: dict | None = None       # parsed JSON when the prompt declares output_schema
    model: str
    model_version: str
    prompt_hash: str                     # SHA-256 of the rendered prompt
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool
    llm_call_id: UUID
