"""Health-check tests for the MQTT/UNS connector (Sprint 2a Task 10).

Hermetic: injects a fake paho client class that synchronously triggers callbacks so
the blocking ``_run_paho_*`` helpers see an immediate CONNACK/SUBACK.

Live (skip-if-down): checks the probe against localhost:1883.
"""
from __future__ import annotations

import socket
from typing import Any

import pytest

from rca_connector_mqtt.health import MqttHealthProbe, _parse_host_port
from rca_connector_mqtt.server import make_mqtt_mcp
from rca_connector_sdk import SubscriptionState
from rca_connector_sdk.health import TestConnectionResponse
from fastmcp import Client


# ---- fake paho client ----

class _FakePahoClient:
    """Fake ``paho.mqtt.client.Client`` that synchronously invokes callbacks."""

    def __init__(self, callback_api_version: Any = None,
                 client_id: str = "", clean_session: bool = True) -> None:
        self.on_connect: Any = None
        self.on_subscribe: Any = None
        self._connected = False
        self._subscriptions: list[str] = []
        self.fail_connect: bool = False

    def connect(self, host: str, port: int, keepalive: int = 60) -> None:
        if self.fail_connect:
            raise OSError("Connection refused")
        self._connected = True
        # Immediately fire on_connect with a success reason code
        if self.on_connect is not None:
            _rc = _SuccessRC()
            self.on_connect(self, None, {}, _rc)

    def loop_start(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, topic: str) -> tuple[int, int]:
        self._subscriptions.append(topic)
        if self.on_subscribe is not None:
            self.on_subscribe(self, None, 1, [_SuccessRC()], None)
        return 0, 1


class _SuccessRC:
    """Minimal reason-code object that looks like a successful CONNACK/SUBACK."""
    is_failure = False

    def __bool__(self) -> bool:
        return True


# Factory: paho.Client is actually called as Client(CallbackAPIVersion.VERSION2, ...)
# Our fake accepts the first positional arg (the API version enum) plus kwargs.
class _FakePahoClientCls:
    """Callable that acts like ``paho.mqtt.client.Client`` class."""

    def __call__(self, callback_api_version: Any = None,
                 client_id: str = "", clean_session: bool = True) -> _FakePahoClient:
        return _FakePahoClient(callback_api_version, client_id, clean_session)


_fake_paho = _FakePahoClientCls()


class _FakePahoClientClsConnectFail:
    def __call__(self, callback_api_version: Any = None,
                 client_id: str = "", clean_session: bool = True) -> _FakePahoClient:
        inst = _FakePahoClient(callback_api_version, client_id, clean_session)
        inst.fail_connect = True
        return inst


_fake_paho_fail = _FakePahoClientClsConnectFail()


def _always_reachable(host: str, port: int, timeout: float) -> bool:
    """Stub the TCP pre-check for hermetic tests — the fake paho client IS the broker."""
    return True


# ---- _parse_host_port unit tests ----

def test_parse_host_port_defaults():
    host, port = _parse_host_port(None, "localhost", 1883)
    assert host == "localhost" and port == 1883


def test_parse_host_port_mqtt_url():
    host, port = _parse_host_port("mqtt://broker.example.com:1884", "localhost", 1883)
    assert host == "broker.example.com" and port == 1884


def test_parse_host_port_host_colon_port():
    host, port = _parse_host_port("mybroker:9883", "localhost", 1883)
    assert host == "mybroker" and port == 9883


# ---- hermetic tests ----

async def test_mqtt_health_success_path():
    """Both sub-checks pass with the fake paho client."""
    probe = MqttHealthProbe(
        broker_host="fake-broker",
        broker_port=1883,
        paho_client_class=_fake_paho,
        reachable_check=_always_reachable,
    )
    checks, version = await probe.run(None, 5.0)
    names = [c.name for c in checks]
    assert names == ["broker_connect", "subscribe"]
    assert checks[0].status == "pass"
    assert checks[1].status == "pass"
    assert version is None


async def test_mqtt_health_failure_path_connect_fails():
    """When connect raises, gate fails and subscribe is skipped."""
    probe = MqttHealthProbe(
        broker_host="dead-broker",
        broker_port=1883,
        paho_client_class=_fake_paho_fail,
        reachable_check=_always_reachable,   # pass the TCP gate so connect() is what fails
    )
    checks, version = await probe.run(None, 5.0)
    assert checks[0].name == "broker_connect"
    assert checks[0].status == "fail"
    assert checks[1].name == "subscribe"
    assert checks[1].status == "skip"
    assert version is None


async def test_mqtt_test_connection_tool_via_mcp():
    """test_connection tool present + returns success=True with the fake broker."""
    mcp = make_mqtt_mcp(
        state=SubscriptionState(),
        broker_host="fake-broker",
        broker_port=1883,
        paho_health_client_class=_fake_paho,
        health_reachable_check=_always_reachable,
    )
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        assert {"uns.browse_namespace", "uns.get_recent_messages",
                "test_connection"} <= tools

        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is True
        assert [c.name for c in resp.checks] == ["broker_connect", "subscribe"]


async def test_mqtt_test_connection_failure_returns_success_false():
    """test_connection returns success=False when broker is unreachable."""
    mcp = make_mqtt_mcp(
        state=SubscriptionState(),
        broker_host="dead-broker",
        broker_port=1883,
        paho_health_client_class=_fake_paho_fail,
        health_reachable_check=_always_reachable,   # pass the TCP gate so connect() is what fails
    )
    async with Client(mcp) as client:
        result = await client.call_tool("test_connection", {"request": {}})
        payload = (result.structured_content
                   if result.structured_content is not None else result.data)
        resp = TestConnectionResponse.model_validate(payload)
        assert resp.success is False
        assert resp.checks[0].name == "broker_connect"
        assert resp.checks[0].status == "fail"


async def test_mqtt_health_unreachable_pre_check_gates_connect():
    """A failing TCP pre-check fails broker_connect fast, without invoking paho.connect."""
    def _never_reachable(host: str, port: int, timeout: float) -> bool:
        return False

    probe = MqttHealthProbe(
        broker_host="filtered-broker",
        broker_port=1883,
        paho_client_class=_fake_paho,          # would succeed if reached — proves the gate ran first
        reachable_check=_never_reachable,
    )
    checks, _ = await probe.run(None, 5.0)
    assert checks[0].name == "broker_connect"
    assert checks[0].status == "fail"
    assert "not reachable" in (checks[0].message or "")
    assert checks[1].name == "subscribe" and checks[1].status == "skip"


# ---- live variant ----

def _broker_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 1883), timeout=2):
            return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _broker_reachable(),
    reason="MQTT broker not reachable at localhost:1883",
)
async def test_mqtt_health_live_against_broker():
    probe = MqttHealthProbe(broker_host="127.0.0.1", broker_port=1883)
    checks, version = await probe.run(None, 10.0)
    names = [c.name for c in checks]
    assert names == ["broker_connect", "subscribe"]
    assert checks[0].status == "pass"
    assert checks[1].status == "pass"
