"""Streaming primitives for long-lived subscription connectors (OPC UA, MQTT/UNS).

These are the reusable pieces of the background-ingest shape: a bounded recent-message
buffer, shared subscription state, and a reconnecting run loop. A streaming connector
runs `run_with_reconnect` in the background to keep a subscription alive and fill
`SubscriptionState`; its request/response MCP tools then read that state.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("rca_connector_sdk.subscription")


class RingBuffer:
    """A bounded FIFO of recent items (oldest dropped past maxlen)."""

    def __init__(self, maxlen: int) -> None:
        self._dq: deque = deque(maxlen=maxlen)

    def append(self, item: Any) -> None:
        self._dq.append(item)

    def snapshot(self) -> list[Any]:
        return list(self._dq)

    def __len__(self) -> int:
        return len(self._dq)


@dataclass
class SubscriptionState:
    """Shared state a background subscription fills and read tools read.

    Concurrency: typically written by a single background ingest thread (the paho/asyncua
    callback) and read by request/response tools on another thread. Individual dict/deque
    operations are atomic under the GIL, but a reader that *iterates* ``current_values`` or
    ``metadata`` while the writer mutates it can hit "dict changed size during iteration".
    Readers must snapshot (copy) before iterating; this is not internally locked.
    """

    current_values: dict[str, Any] = field(default_factory=dict)   # latest value per key
    metadata: dict[str, Any] = field(default_factory=dict)         # e.g. BIRTH aliases/units
    recent: RingBuffer = field(default_factory=lambda: RingBuffer(1000))


async def run_with_reconnect(
    consume: Callable[[], Awaitable[None]],
    *,
    stop: asyncio.Event,
    base_backoff: float = 0.5,
    max_backoff: float = 30.0,
) -> None:
    """Keep a subscription alive: call ``consume`` (which runs until it returns/raises),
    reconnecting with exponential backoff on failure, until ``stop`` is set.

    ``consume`` should block while connected and raise on disconnect. A clean return
    resets the backoff and the loop re-enters (until stop)."""
    backoff = base_backoff
    while not stop.is_set():
        try:
            await consume()
            backoff = base_backoff
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if stop.is_set():
                break
            _log.warning(
                "subscription consume failed (%s: %s); reconnecting in %.1fs",
                type(exc).__name__, exc, backoff,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
                break  # stop was set during backoff
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff)


__all__ = ["RingBuffer", "SubscriptionState", "run_with_reconnect"]
