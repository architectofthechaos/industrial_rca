"""Health probe for the MQTT/UNS connector (Sprint 2a Task 10).

Sub-checks (gate first):
  broker_connect — paho connect + CONNACK, then disconnect
  subscribe      — subscribe to ``spBv1.0/#`` + SUBACK, then disconnect

Blocking paho calls are run via ``asyncio.to_thread`` so as not to block the event
loop.  The probe accepts a *paho client class* (or factory callable) for hermetic
testing — pass a fake that records connect/subscribe/disconnect calls.
"""
from __future__ import annotations

import asyncio
import socket
from typing import Any
from urllib.parse import urlparse

from rca_connector_sdk.health import (
    CheckResult,
    ProbeResult,
    skipped_check,
    timed_check,
)

_TOPIC = "spBv1.0/#"


def _parse_host_port(base_url: str | None, default_host: str, default_port: int) -> tuple[str, int]:
    """Parse ``mqtt://host:port`` or ``host:port`` override; fall back to defaults."""
    if not base_url:
        return default_host, default_port
    if "://" not in base_url:
        base_url = f"mqtt://{base_url}"
    parsed = urlparse(base_url)
    host = parsed.hostname or default_host
    port = parsed.port or default_port
    return host, port


def _broker_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Quick TCP check: is the broker accepting connections?"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _run_paho_connect(paho_client_cls: Any, host: str, port: int, timeout: float) -> str:
    """Blocking: connect + CONNACK + disconnect.  Called via asyncio.to_thread."""
    import paho.mqtt.client as mqtt  # noqa: PLC0415

    result: list[Any] = []   # [True] on success, [Exception] on failure

    client = paho_client_cls(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="rca-health-connect",
        clean_session=True,
    )

    def on_connect(c: Any, userdata: Any, flags: Any,
                   reason_code: Any, properties: Any = None) -> None:
        if hasattr(reason_code, "is_failure") and reason_code.is_failure:
            result.append(ConnectionError(f"CONNACK refused: {reason_code}"))
        else:
            result.append(True)

    client.on_connect = on_connect
    try:
        client.connect(host, port, keepalive=5)
        client.loop_start()
        import time
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    if not result:
        raise TimeoutError(f"CONNACK not received within {timeout}s")
    if isinstance(result[0], Exception):
        raise result[0]
    return f"broker {host}:{port} accepted connection"


def _run_paho_subscribe(paho_client_cls: Any, host: str, port: int,
                        topic: str, timeout: float) -> str:
    """Blocking: connect + subscribe + SUBACK + disconnect.  Called via asyncio.to_thread."""
    import paho.mqtt.client as mqtt  # noqa: PLC0415

    result: list[Any] = []

    client = paho_client_cls(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="rca-health-subscribe",
        clean_session=True,
    )

    def on_connect(c: Any, userdata: Any, flags: Any,
                   reason_code: Any, properties: Any = None) -> None:
        if not (hasattr(reason_code, "is_failure") and reason_code.is_failure):
            c.subscribe(topic)

    def on_subscribe(c: Any, userdata: Any, mid: Any,
                     reason_codes: Any, properties: Any = None) -> None:
        result.append(True)

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    try:
        client.connect(host, port, keepalive=5)
        client.loop_start()
        import time
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    if not result:
        raise TimeoutError(f"SUBACK not received for {topic!r} within {timeout}s")
    return f"SUBACK on {topic}"


class MqttHealthProbe:
    """HealthProbe implementation for the MQTT/UNS connector.

    ``paho_client_class`` is injected for hermetic tests.  The default (None) imports
    ``paho.mqtt.client.Client`` lazily so the probe compiles without paho installed.
    """

    def __init__(
        self,
        *,
        broker_host: str,
        broker_port: int = 1883,
        paho_client_class: Any | None = None,
    ) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._paho_cls = paho_client_class

    def _get_paho_cls(self) -> Any:
        if self._paho_cls is not None:
            return self._paho_cls
        import paho.mqtt.client as mqtt  # noqa: PLC0415 — paho is a dep of this package
        return mqtt.Client

    async def run(self, base_url: str | None, timeout: float) -> ProbeResult:
        host, port = _parse_host_port(base_url, self._broker_host, self._broker_port)
        checks: list[CheckResult] = []
        paho_cls = self._get_paho_cls()

        # 1. broker_connect — TCP connect + CONNACK
        async def _connect() -> str | None:
            return await asyncio.to_thread(
                _run_paho_connect, paho_cls, host, port, timeout
            )

        gate = await timed_check("broker_connect", _connect)
        checks.append(gate)

        if gate.status == "fail":
            checks.append(skipped_check("subscribe", "skipped: broker_connect failed"))
            return checks, None

        # 2. subscribe — SUBACK on spBv1.0/#
        async def _subscribe() -> str | None:
            return await asyncio.to_thread(
                _run_paho_subscribe, paho_cls, host, port, _TOPIC, timeout
            )

        checks.append(await timed_check("subscribe", _subscribe))

        return checks, None


__all__ = ["MqttHealthProbe", "_parse_host_port", "_broker_reachable"]
