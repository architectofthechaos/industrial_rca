"""rca_llm — the single non-bypassable LLM client + prompt registry (Sprint 3 WI1).

Every LLM call in the platform routes through ``LLMClientImpl.complete`` / ``.embed``:
provenance, content-addressed caching (replay), per-probe token-budget enforcement, and
``llm_calls`` audit are guaranteed. Live Anthropic/Voyage transports are imported lazily
(``rca_llm.transports``) so the hermetic suite runs without the SDKs.
"""
from .audit import AuditSink, InMemoryAuditSink, LlmCallRecord, NullAuditSink
from .cache import InMemoryResponseCache, ResponseCache, prompt_hash
from .client import (
    CompletionResult,
    CompletionTransport,
    EmbeddingTransport,
    LLMClient,
    LLMClientImpl,
    NoUpstreamTransport,
)
from .registry import (
    Prompt,
    PromptRegistry,
    PromptValidationError,
    default_registry,
    parse_prompt,
)

__version__ = "0.0.1"

__all__ = [
    "LLMClient", "LLMClientImpl", "CompletionTransport", "CompletionResult",
    "EmbeddingTransport", "NoUpstreamTransport",
    "Prompt", "PromptRegistry", "PromptValidationError", "parse_prompt", "default_registry",
    "ResponseCache", "InMemoryResponseCache", "prompt_hash",
    "AuditSink", "InMemoryAuditSink", "NullAuditSink", "LlmCallRecord",
]
