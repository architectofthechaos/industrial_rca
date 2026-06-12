"""Deterministic transports for hermetic tests (Sprint 3 WI1).

``ScriptedCompletionTransport`` maps a prompt *name* to a canned response so agent legs can
run end-to-end with no network and no SDK; ``HashEmbeddingTransport`` produces stable,
deterministic embedding vectors from text content. Shared by the llm package's own tests and
by the agent-package tests (WI2-5), so the whole probe replays byte-identically.
"""
from __future__ import annotations

import hashlib

from .client import CompletionResult
from .embedding_config import embedding_dim


class ScriptedCompletionTransport:
    """Returns a scripted response per prompt name. Records every call for assertions."""

    def __init__(self, responses: dict[str, str], *, default: str | None = None) -> None:
        self._responses = dict(responses)
        self._default = default
        self.calls: list[dict] = []

    async def complete(
        self, *, model: str, rendered_prompt: str, temperature: float, max_tokens: int,
        output_schema: dict | None,
    ) -> CompletionResult:
        # Match on which scripted key appears in the rendered prompt's leading marker, else
        # fall back to the single response / default. Tests usually use one prompt at a time.
        content = None
        for key, value in self._responses.items():
            if key in rendered_prompt:
                content = value
                break
        if content is None:
            content = self._default if self._default is not None else next(
                iter(self._responses.values()), "{}")
        self.calls.append({"model": model, "rendered_prompt": rendered_prompt,
                           "max_tokens": max_tokens})
        return CompletionResult(content=content, model_version=f"{model}-test",
                                input_tokens=max(1, len(rendered_prompt) // 4),
                                output_tokens=max(1, len(content) // 4))


class FixedCompletionTransport:
    """Always returns the same content with fixed token counts — for budget tests."""

    def __init__(self, content: str = "{}", *, input_tokens: int = 100,
                 output_tokens: int = 50) -> None:
        self._content = content
        self._in = input_tokens
        self._out = output_tokens
        self.call_count = 0

    async def complete(self, *, model: str, **_: object) -> CompletionResult:
        self.call_count += 1
        return CompletionResult(content=self._content, model_version=f"{model}-test",
                                input_tokens=self._in, output_tokens=self._out)


class HashEmbeddingTransport:
    """Deterministic embeddings: each text -> a fixed-dim vector seeded from its SHA-256."""

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim if dim is not None else embedding_dim()
        self.call_count = 0

    async def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:  # noqa: ARG002
        self.call_count += 1
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            out.append([digest[i % len(digest)] / 255.0 for i in range(self._dim)])
        return out


__all__ = [
    "ScriptedCompletionTransport", "FixedCompletionTransport", "HashEmbeddingTransport",
]
