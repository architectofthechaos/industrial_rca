"""The single non-bypassable LLM abstraction (Sprint 3 WI1).

Every LLM call in the platform goes through ``LLMClient.complete`` / ``.embed``. The client
renders a registry prompt, hashes it, checks the content-addressed cache, enforces the
per-probe token budget, calls the upstream transport (on a miss), parses structured output,
writes an audit row, and returns a fully-provenanced ``LLMResponse``.

Determinism: with ``replay_from_cache=True`` a cache hit returns the cached response and makes
NO upstream call — the basis for byte-identical probe replays (excluding generation
timestamps). The live Anthropic/Voyage transports import their SDKs lazily, so the hermetic
suite (replay-only) runs without them installed.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from rca_contracts import LLMResponse, TokenBudget, TokenBudgetExceeded

from .audit import AuditSink, LlmCallRecord, NullAuditSink
from .cache import InMemoryResponseCache, ResponseCache, prompt_hash
from .registry import Prompt, PromptRegistry, default_registry


# --------------------------------------------------------------------- transports
class CompletionResult:
    """Raw upstream completion (before caching/provenance wrapping)."""

    def __init__(self, *, content: str, model_version: str, input_tokens: int,
                 output_tokens: int) -> None:
        self.content = content
        self.model_version = model_version
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class CompletionTransport(Protocol):
    async def complete(
        self, *, model: str, rendered_prompt: str, temperature: float, max_tokens: int,
        output_schema: dict | None,
    ) -> CompletionResult: ...


class EmbeddingTransport(Protocol):
    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]: ...


class NoUpstreamTransport:
    """Raises if reached — wires the replay-only hermetic path so any accidental upstream
    call fails loudly instead of hitting the network."""

    async def complete(self, **_: Any) -> CompletionResult:
        raise RuntimeError("upstream completion attempted on a replay-only transport "
                           "(cache miss with replay_from_cache=True)")

    async def embed(self, **_: Any) -> list[list[float]]:
        raise RuntimeError("upstream embedding attempted on a replay-only transport")


# --------------------------------------------------------------------- client
class LLMClient(Protocol):
    async def complete(
        self, prompt_name: str, prompt_version: str, variables: dict[str, Any], *,
        correlation_id: str, budget: TokenBudget | None = None,
        probe_run_id: UUID | None = None, replay_from_cache: bool = False,
    ) -> LLMResponse: ...

    async def embed(
        self, text: str | list[str], *, model: str = "voyage-3", correlation_id: str,
    ) -> list[list[float]]: ...


class LLMClientImpl:
    def __init__(
        self, *,
        registry: PromptRegistry | None = None,
        transport: CompletionTransport | None = None,
        embedding_transport: EmbeddingTransport | None = None,
        cache: ResponseCache | None = None,
        audit: AuditSink | None = None,
    ) -> None:
        # Explicit `is None` checks, not `or`: InMemoryResponseCache defines __len__, so an
        # empty (shared) cache is falsy and `cache or ...` would silently swap it for a fresh one.
        self._registry = registry if registry is not None else default_registry()
        self._transport = transport if transport is not None else NoUpstreamTransport()
        self._embeddings = (embedding_transport if embedding_transport is not None
                            else NoUpstreamTransport())
        self._cache = cache if cache is not None else InMemoryResponseCache()
        self._audit = audit if audit is not None else NullAuditSink()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _estimate_input_tokens(rendered: str) -> int:
        # cheap heuristic for the pre-call budget gate (~4 chars/token); real counts come back
        # from the transport and are what get charged.
        return max(1, len(rendered) // 4)

    async def complete(
        self, prompt_name: str, prompt_version: str, variables: dict[str, Any], *,
        correlation_id: str, budget: TokenBudget | None = None,
        probe_run_id: UUID | None = None, replay_from_cache: bool = False,
    ) -> LLMResponse:
        prompt: Prompt = self._registry.get_prompt(prompt_name, prompt_version)
        rendered = prompt.render(variables)
        phash = prompt_hash(rendered)

        cached = await self._cache.get(phash)
        if cached is not None:
            response = self._response_from_cache(cached, phash, prompt)
            await self._record(response, prompt, correlation_id, probe_run_id, rendered,
                               cached=True)
            return response

        if replay_from_cache:
            # No cache entry and we promised no upstream — fail loudly (hermetic invariant).
            raise RuntimeError(
                f"replay_from_cache=True but no cached response for {prompt_name}/{prompt_version}"
                f" (prompt_hash={phash[:12]}…)")

        # Budget gate BEFORE the upstream call.
        est_input = self._estimate_input_tokens(rendered)
        if budget is not None and budget.would_exceed(
                input_tokens=est_input, output_tokens=prompt.max_tokens):
            raise TokenBudgetExceeded(
                f"{prompt_name}/{prompt_version} would exceed token budget "
                f"(in_used={budget.input_used}/{budget.input_tokens_limit}, "
                f"out_used={budget.output_used}/{budget.output_tokens_limit})",
                budget=budget)

        started = time.monotonic()
        result = await self._transport.complete(
            model=prompt.model, rendered_prompt=rendered, temperature=prompt.temperature,
            max_tokens=prompt.max_tokens, output_schema=prompt.output_schema)
        latency_ms = int((time.monotonic() - started) * 1000)

        if budget is not None:
            budget.charge(input_tokens=result.input_tokens, output_tokens=result.output_tokens)

        structured = self._parse_structured(result.content, prompt.output_schema)
        response = LLMResponse(
            content=result.content, structured=structured, model=prompt.model,
            model_version=result.model_version, prompt_hash=phash,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            latency_ms=latency_ms, cached=False, llm_call_id=uuid4())
        await self._cache.put(phash, {
            "content": result.content, "structured": structured,
            "model": prompt.model, "model_version": result.model_version,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
        await self._record(response, prompt, correlation_id, probe_run_id, rendered,
                           cached=False)
        return response

    def _response_from_cache(self, cached: dict[str, Any], phash: str,
                             prompt: Prompt) -> LLMResponse:
        return LLMResponse(
            content=cached["content"], structured=cached.get("structured"),
            model=cached.get("model", prompt.model),
            model_version=cached.get("model_version", "cache"), prompt_hash=phash,
            input_tokens=cached.get("input_tokens", 0),
            output_tokens=cached.get("output_tokens", 0), latency_ms=0, cached=True,
            llm_call_id=uuid4())

    @staticmethod
    def _parse_structured(content: str, output_schema: dict | None) -> dict | None:
        if output_schema is None:
            return None
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _record(self, response: LLMResponse, prompt: Prompt, correlation_id: str,
                      probe_run_id: UUID | None, rendered: str, *, cached: bool) -> None:
        await self._audit.record(LlmCallRecord(
            llm_call_id=response.llm_call_id, correlation_id=correlation_id,
            probe_run_id=probe_run_id, prompt_name=prompt.name, prompt_version=prompt.version,
            prompt_hash=response.prompt_hash, model=response.model,
            model_version=response.model_version, temperature=prompt.temperature,
            input_tokens=response.input_tokens, output_tokens=response.output_tokens,
            latency_ms=response.latency_ms, cached=cached,
            request_payload={"rendered_prompt": rendered, "variables_keys": prompt.variables},
            response_payload={"content": response.content, "structured": response.structured},
            created_at=self._now()))

    async def embed(
        self, text: str | list[str], *, model: str = "voyage-3", correlation_id: str,
    ) -> list[list[float]]:
        texts = [text] if isinstance(text, str) else list(text)
        return await self._embeddings.embed(model=model, texts=texts)


__all__ = [
    "LLMClient", "LLMClientImpl", "CompletionTransport", "CompletionResult",
    "EmbeddingTransport", "NoUpstreamTransport",
]
