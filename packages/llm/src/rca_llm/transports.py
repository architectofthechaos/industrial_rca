"""Live upstream transports (Sprint 3 WI1) — Anthropic completions + Voyage embeddings.

Both import their SDKs LAZILY (inside ``__init__``) and resolve API keys through the shared
``EnvSecretResolver`` (same pattern as connector auth, §1.6), so importing this module — and
running the hermetic suite — never requires the SDKs or live keys.
"""
from __future__ import annotations

from rca_connector_sdk import EnvSecretResolver
from rca_connector_sdk.secrets import SecretResolver

from .client import CompletionResult


class AnthropicTransport:
    def __init__(self, *, api_key_ref: str = "env:ANTHROPIC_API_KEY",
                 secret_resolver: SecretResolver | None = None) -> None:
        import anthropic  # lazy — only when a live transport is actually constructed

        resolver = secret_resolver or EnvSecretResolver()
        api_key = resolver.resolve(api_key_ref)
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(
        self, *, model: str, rendered_prompt: str, temperature: float, max_tokens: int,
        output_schema: dict | None,
    ) -> CompletionResult:
        system = ("Respond with a single JSON object matching the requested schema; no prose."
                  if output_schema is not None
                  else "You are a precise reliability-engineering assistant.")
        message = await self._client.messages.create(
            model=model, max_tokens=max_tokens, temperature=temperature, system=system,
            messages=[{"role": "user", "content": rendered_prompt}])
        content = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text")
        return CompletionResult(
            content=content, model_version=message.model,
            input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens)


class VoyageEmbeddingTransport:
    def __init__(self, *, api_key_ref: str = "env:VOYAGE_API_KEY",
                 secret_resolver: SecretResolver | None = None) -> None:
        import voyageai  # lazy

        resolver = secret_resolver or EnvSecretResolver()
        api_key = resolver.resolve(api_key_ref)
        self._client = voyageai.AsyncClient(api_key=api_key)

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        result = await self._client.embed(texts, model=model)
        return list(result.embeddings)


__all__ = ["AnthropicTransport", "VoyageEmbeddingTransport"]
