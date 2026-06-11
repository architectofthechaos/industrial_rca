"""Health probe for the OPC UA connector (Sprint 2a Task 10).

Sub-checks (gate first):
  endpoint_reachability — TCP connect to host:port parsed from the opc.tcp:// endpoint URL
  session               — asyncua.Client(url).connect() + disconnect
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from rca_connector_sdk.health import (
    CheckResult,
    ProbeResult,
    skipped_check,
    timed_check,
)

# Type alias for the asyncua client constructor (injectable for hermetic tests).
OpcUaClientFactory = Callable[[str], Any]


def _default_opcua_factory(url: str) -> Any:
    from asyncua import Client  # noqa: PLC0415 — lazy import; asyncua is a dep of this package
    return Client(url=url)


class OpcUaHealthProbe:
    """HealthProbe implementation for the OPC UA connector."""

    def __init__(
        self,
        configured_endpoint: str,
        *,
        opcua_client_factory: OpcUaClientFactory | None = None,
    ) -> None:
        self._configured_endpoint = configured_endpoint
        self._opcua_factory = opcua_client_factory or _default_opcua_factory

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        """Run sub-checks against the endpoint URL.

        ``base_url`` may carry an ``opc.tcp://host:port/...`` override; when None
        the configured endpoint is used.
        """
        endpoint = base_url or self._configured_endpoint
        checks: list[CheckResult] = []

        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port or 4840

        # 1. endpoint_reachability — TCP connect
        async def _tcp() -> str | None:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return f"tcp://{host}:{port} reachable"

        gate = await timed_check("endpoint_reachability", _tcp)
        checks.append(gate)

        if gate.status == "fail":
            checks.append(skipped_check("session", "skipped: endpoint_reachability failed"))
            return checks, None

        # 2. session — asyncua connect + disconnect
        async def _session() -> str | None:
            client = self._opcua_factory(endpoint)
            await asyncio.wait_for(client.connect(), timeout=timeout)
            try:
                server_info = await client.get_namespace_array()
                return f"namespaces={len(server_info)}"
            finally:
                await client.disconnect()

        checks.append(await timed_check("session", _session))

        return checks, None


__all__ = ["OpcUaHealthProbe", "OpcUaClientFactory", "_default_opcua_factory"]
