"""LLM client: provenance, content-addressed caching/replay, budget enforcement, audit.

All hermetic — no SDK, no network. Replay is proven by sharing a cache with a transport that
raises if reached (NoUpstreamTransport)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from rca_contracts import TokenBudget, TokenBudgetExceeded

from rca_llm.audit import InMemoryAuditSink
from rca_llm.cache import InMemoryResponseCache
from rca_llm.client import LLMClientImpl, NoUpstreamTransport
from rca_llm.registry import PromptRegistry, parse_prompt
from rca_llm.testing import FixedCompletionTransport, HashEmbeddingTransport, ScriptedCompletionTransport

_PROMPT = """---
name: echo
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 200
variables: [marker, value]
output_schema:
  type: object
  properties:
    seen: {type: string}
---
echo prompt {{ marker }} value={{ value }}
"""


def _registry() -> PromptRegistry:
    reg = PromptRegistry()
    reg.add(parse_prompt(_PROMPT))
    return reg


def _scripted(content: str = '{"seen": "ok"}') -> ScriptedCompletionTransport:
    return ScriptedCompletionTransport({"echo prompt": content})


async def test_complete_returns_full_provenance_and_parses_structured():
    client = LLMClientImpl(registry=_registry(), transport=_scripted(),
                           cache=InMemoryResponseCache(), audit=InMemoryAuditSink())
    resp = await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                                 correlation_id="corr-1")
    assert resp.cached is False
    assert resp.model == "claude-opus-4-8"
    assert resp.model_version == "claude-opus-4-8-test"
    assert len(resp.prompt_hash) == 64               # sha-256 hex
    assert resp.input_tokens > 0 and resp.output_tokens > 0
    assert resp.structured == {"seen": "ok"}
    assert resp.llm_call_id is not None


async def test_replay_from_cache_returns_cached_with_no_upstream_call():
    cache = InMemoryResponseCache()
    # 1) record with a scripted transport
    rec = LLMClientImpl(registry=_registry(), transport=_scripted(), cache=cache)
    first = await rec.complete("echo", "v1", {"marker": "M", "value": "V"},
                               correlation_id="c")
    assert first.cached is False
    # 2) replay against a transport that raises if reached -> proves no upstream call
    replay = LLMClientImpl(registry=_registry(), transport=NoUpstreamTransport(), cache=cache)
    second = await replay.complete("echo", "v1", {"marker": "M", "value": "V"},
                                   correlation_id="c", replay_from_cache=True)
    assert second.cached is True
    # byte-identical content/structured (excluding generation timestamps + call id)
    assert second.content == first.content
    assert second.structured == first.structured
    assert second.prompt_hash == first.prompt_hash


async def test_replay_from_cache_with_empty_cache_raises():
    client = LLMClientImpl(registry=_registry(), transport=NoUpstreamTransport(),
                           cache=InMemoryResponseCache())
    with pytest.raises(RuntimeError):
        await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                              correlation_id="c", replay_from_cache=True)


async def test_budget_overrun_raises_token_budget_exceeded():
    transport = FixedCompletionTransport(content='{"seen":"x"}', input_tokens=100,
                                         output_tokens=50)
    client = LLMClientImpl(registry=_registry(), transport=transport,
                           cache=InMemoryResponseCache())
    budget = TokenBudget(input_tokens_limit=5, output_tokens_limit=5)  # tiny
    with pytest.raises(TokenBudgetExceeded):
        await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                              correlation_id="c", budget=budget)
    assert transport.call_count == 0   # raised BEFORE the upstream call


async def test_budget_charged_on_success():
    transport = FixedCompletionTransport(content='{"seen":"x"}', input_tokens=30,
                                         output_tokens=10)
    client = LLMClientImpl(registry=_registry(), transport=transport,
                           cache=InMemoryResponseCache())
    budget = TokenBudget(input_tokens_limit=1000, output_tokens_limit=1000)
    await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                          correlation_id="c", budget=budget)
    assert budget.input_used == 30 and budget.output_used == 10


async def test_audit_records_call_with_probe_linkage():
    audit = InMemoryAuditSink()
    probe_id = uuid4()
    client = LLMClientImpl(registry=_registry(), transport=_scripted(),
                           cache=InMemoryResponseCache(), audit=audit)
    resp = await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                                 correlation_id="corr-42", probe_run_id=probe_id)
    rows = audit.for_probe(probe_id)
    assert len(rows) == 1
    assert rows[0].prompt_name == "echo"
    assert rows[0].prompt_hash == resp.prompt_hash
    assert rows[0].correlation_id == "corr-42"
    assert rows[0].input_tokens == resp.input_tokens


async def test_embed_is_deterministic():
    client = LLMClientImpl(registry=_registry(), embedding_transport=HashEmbeddingTransport(dim=8))
    a = await client.embed(["mechanical seal leak", "bearing wear"], correlation_id="c")
    b = await client.embed(["mechanical seal leak", "bearing wear"], correlation_id="c")
    assert a == b
    assert len(a) == 2 and len(a[0]) == 8
    assert a[0] != a[1]   # different text -> different vector


async def test_same_inputs_hit_cache_on_second_call_same_client():
    cache = InMemoryResponseCache()
    transport = _scripted()
    client = LLMClientImpl(registry=_registry(), transport=transport, cache=cache)
    await client.complete("echo", "v1", {"marker": "M", "value": "V"}, correlation_id="c")
    n_calls_after_first = len(transport.calls)
    second = await client.complete("echo", "v1", {"marker": "M", "value": "V"},
                                   correlation_id="c")
    assert second.cached is True
    assert len(transport.calls) == n_calls_after_first   # no new upstream call
