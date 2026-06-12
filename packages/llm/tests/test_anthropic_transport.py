"""Live-transport unit tests (Sprint 5 G20).

Exercise ``AnthropicTransport`` against a FAKE anthropic client (no network) — the hermetic
suite uses ``ScriptedCompletionTransport`` and never hit this path, which is why the
``temperature`` deprecation on ``claude-opus-4-8`` was invisible until the first live run.

Skips when the ``rca-llm[live]`` SDK isn't installed, so CI without the extra stays clean.
"""
from __future__ import annotations

import types

import pytest

anthropic = pytest.importorskip("anthropic")
import httpx  # noqa: E402  (only needed when anthropic is present)


def _bad_request(message: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(
        message,
        response=httpx.Response(400, request=httpx.Request("POST", "http://test")),
        body=None,
    )


class _FakeMessages:
    def __init__(self, *, reject_temperature: bool) -> None:
        self.reject_temperature = reject_temperature
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.reject_temperature and "temperature" in kwargs:
            raise _bad_request("`temperature` is deprecated for this model.")
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="hi")],
            model=kwargs["model"],
            usage=types.SimpleNamespace(input_tokens=3, output_tokens=2),
        )


class _FakeClient:
    def __init__(self, messages) -> None:
        self.messages = messages


class _DummyResolver:
    def resolve(self, ref: str) -> str:
        return "dummy-key"


def _transport():
    from rca_llm.transports import AnthropicTransport

    return AnthropicTransport(secret_resolver=_DummyResolver())


@pytest.mark.asyncio
async def test_retries_without_temperature_when_model_rejects_it():
    t = _transport()
    t._client = _FakeClient(_FakeMessages(reject_temperature=True))
    res = await t.complete(model="claude-opus-4-8", rendered_prompt="hi", temperature=0.0,
                           max_tokens=20, output_schema=None)
    assert res.content == "hi"
    calls = t._client.messages.calls
    assert "temperature" in calls[0]          # first attempt sent it
    assert "temperature" not in calls[1]      # retry dropped it
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_keeps_temperature_for_models_that_accept_it():
    t = _transport()
    t._client = _FakeClient(_FakeMessages(reject_temperature=False))
    res = await t.complete(model="claude-haiku-4-5-20251001", rendered_prompt="hi",
                           temperature=0.0, max_tokens=20, output_schema=None)
    assert res.content == "hi"
    calls = t._client.messages.calls
    assert len(calls) == 1 and calls[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_memoizes_rejection_no_repeated_400():
    t = _transport()
    t._client = _FakeClient(_FakeMessages(reject_temperature=True))
    await t.complete(model="claude-opus-4-8", rendered_prompt="a", temperature=0.0,
                     max_tokens=20, output_schema=None)
    n = len(t._client.messages.calls)         # 2: reject + retry
    await t.complete(model="claude-opus-4-8", rendered_prompt="b", temperature=0.0,
                     max_tokens=20, output_schema=None)
    # second call is memoized: a single create, no temperature, no wasted 400
    assert len(t._client.messages.calls) == n + 1
    assert "temperature" not in t._client.messages.calls[-1]


@pytest.mark.asyncio
async def test_non_temperature_400_propagates():
    class _OtherBadRequest(_FakeMessages):
        async def create(self, **kwargs):
            self.calls.append(dict(kwargs))
            raise _bad_request("max_tokens: must be <= model limit")

    t = _transport()
    t._client = _FakeClient(_OtherBadRequest(reject_temperature=True))
    with pytest.raises(anthropic.BadRequestError):
        await t.complete(model="claude-opus-4-8", rendered_prompt="x", temperature=0.0,
                         max_tokens=999999, output_schema=None)
