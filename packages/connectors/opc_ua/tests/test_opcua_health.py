"""Health-check tests for the OPC UA connector (Sprint 2a Task 10).

Hermetic:
 - endpoint_reachability: starts a local asyncio TCP echo server on an ephemeral port.
 - session: injects a fake asyncua.Client via the probe's ``opcua_client_factory`` param.

Live (skip-if-down): checks the probe against the real OPC UA sim at localhost:4840.
"""
from __future__ import annotations

import asyncio
import socket

import pytest

from rca_connector_opc_ua.health import OpcUaHealthProbe
from rca_connector_opc_ua.server import make_opcua_mcp
from rca_connector_sdk.health import TestConnectionResponse
from fastmcp import Client


# ---- local TCP echo server for reachability tests ----

async def _start_echo_server() -> tuple[asyncio.Server, int]:
    """Start a server on an ephemeral port; return (server, port)."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


# ---- fake asyncua.Client ----

class _FakeOpcUaClient:
    """Fake asyncua.Client for hermetic session tests."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_namespace_array(self) -> list[str]:
        return ["http://opcfoundation.org/UA/", "urn:rca:sim:refplant"]


# ---- hermetic tests ----

async def test_opcua_health_success_path():
    """Both sub-checks pass: TCP port open + fake asyncua session."""
    server, port = await _start_echo_server()
    endpoint = f"opc.tcp://127.0.0.1:{port}/sim"
    try:
        probe = OpcUaHealthProbe(
            endpoint,
            opcua_client_factory=_FakeOpcUaClient,
        )
        checks, version = await probe.run(None, 5.0)
        names = [c.name for c in checks]
        assert names == ["endpoint_reachability", "session"]
        assert checks[0].status == "pass"
        assert checks[1].status == "pass"
        assert version is None
    finally:
        server.close()
        await server.wait_closed()


async def test_opcua_health_gate_fails_when_port_closed():
    """endpoint_reachability fails when port is not listening; session is skipped."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # socket is closed — port is now free (not listening)

    endpoint = f"opc.tcp://127.0.0.1:{port}/sim"
    probe = OpcUaHealthProbe(endpoint, opcua_client_factory=_FakeOpcUaClient)
    checks, version = await probe.run(None, 2.0)
    assert checks[0].name == "endpoint_reachability"
    assert checks[0].status == "fail"
    assert checks[1].name == "session"
    assert checks[1].status == "skip"
    assert version is None


async def test_opcua_test_connection_tool_via_mcp():
    """test_connection tool present in the MCP server + returns expected check names."""
    server, port = await _start_echo_server()
    endpoint = f"opc.tcp://127.0.0.1:{port}/sim"
    try:
        mcp = make_opcua_mcp(
            endpoint=endpoint,
            namespace_uri="urn:test",
            opcua_health_factory=_FakeOpcUaClient,
        )
        async with Client(mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            assert {"opc_ua.get_current_values", "test_connection"} <= tools

            result = await client.call_tool("test_connection", {"request": {}})
            payload = (result.structured_content
                       if result.structured_content is not None else result.data)
            resp = TestConnectionResponse.model_validate(payload)
            assert resp.success is True
            assert [c.name for c in resp.checks] == ["endpoint_reachability", "session"]
    finally:
        server.close()
        await server.wait_closed()


async def test_opcua_test_connection_failure():
    """When port is closed, test_connection returns success=False."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    endpoint = f"opc.tcp://127.0.0.1:{port}/sim"
    mcp = make_opcua_mcp(
        endpoint=endpoint,
        namespace_uri="urn:test",
        opcua_health_factory=_FakeOpcUaClient,
    )
    async with Client(mcp) as client:
        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is False
        assert resp.checks[0].name == "endpoint_reachability"
        assert resp.checks[0].status == "fail"


# ---- live variant ----

OPCUA_ENDPOINT = "opc.tcp://127.0.0.1:4840"


def _opcua_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 4840), timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _opcua_reachable(),
    reason="OPC UA server not reachable at localhost:4840",
)
async def test_opcua_health_live_against_simulator():
    probe = OpcUaHealthProbe(OPCUA_ENDPOINT)
    checks, version = await probe.run(None, 10.0)
    names = [c.name for c in checks]
    assert names == ["endpoint_reachability", "session"]
    assert checks[0].status == "pass"
    assert checks[1].status == "pass"
