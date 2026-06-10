"""Retry / circuit-breaker around source calls (tenacity)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .errors import SourceTimeout, SourceUnavailable

T = TypeVar("T")

# transient failures worth retrying
_RETRYABLE = (SourceUnavailable, SourceTimeout, httpx.TransportError, httpx.TimeoutException)


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    max_wait_seconds: float = 2.0,
) -> T:
    """Call ``fn`` with bounded retries on transient errors; reraises the last failure."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=0.01, max=max_wait_seconds),
        reraise=True,
    ):
        with attempt:
            return await fn()
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["with_retry"]
