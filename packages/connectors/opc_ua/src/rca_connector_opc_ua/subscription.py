"""Background OPC UA subscription — keeps current values fresh with reconnect.

Built on the SDK streaming primitives (run_with_reconnect + SubscriptionState). Fills
state.current_values keyed by NodeId string identifier (the signal key) on each data change.
Read tools / callers read that cache; this is the "subscribe survives restart" path.
"""
from __future__ import annotations

import asyncio

from asyncua import Client, ua
from rca_connector_sdk import EventSink, NullEventSink, SubscriptionState, run_with_reconnect


class OpcUaSubscription:
    def __init__(
        self,
        *,
        endpoint: str,
        namespace_uri: str,
        handles: list[str],
        state: SubscriptionState,
        event_sink: EventSink | None = None,
        period_ms: int = 500,
    ) -> None:
        self.endpoint = endpoint
        self.namespace_uri = namespace_uri
        self.handles = handles
        self.state = state
        self.event_sink = event_sink or NullEventSink()
        self.period_ms = period_ms

    async def run(self, stop: asyncio.Event) -> None:
        state = self.state
        sink = self.event_sink

        class _Handler:
            def datachange_notification(self, node, val, data):  # noqa: ANN001
                key = node.nodeid.Identifier
                state.current_values[key] = val
                # Alias-discovery seam: surface the raw source tag for MAR mapping.
                # Emit the tag only — the live value stays out of event consumers.
                sink.emit({"source": "opc_ua", "raw_tag": key})

        async def consume() -> None:
            async with Client(self.endpoint) as client:
                idx = await client.get_namespace_index(self.namespace_uri)
                sub = await client.create_subscription(self.period_ms, _Handler())
                try:
                    nodes = [client.get_node(ua.NodeId(h, idx)) for h in self.handles]  # type: ignore[arg-type]
                    await sub.subscribe_data_change(nodes)
                    await stop.wait()          # stay subscribed until asked to stop
                finally:
                    await sub.delete()         # always release the server-side subscription

        await run_with_reconnect(consume, stop=stop)


__all__ = ["OpcUaSubscription"]
