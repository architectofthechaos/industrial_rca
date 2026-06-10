"""S13.8 parity: MQTT/UNS connector against the REAL EPIC-002 broker + publisher.

Subscribes via paho to mosquitto at localhost:1883 (native protocol; never imports
rca_simulator) and asserts the connector decodes the live Sparkplug B stream into the
canonical namespace tree + recent messages. Skips when the broker is down.
Run with: `task parity:mqtt`.
"""
import asyncio
import json
import os
import socket

import pytest
from fastmcp import Client as McpClient
from rca_connector_sdk import SubscriptionState
from rca_contracts import ToolResponse

from rca_connector_mqtt.models import NamespaceTree, RecentMessages
from rca_connector_mqtt.server import make_mqtt_mcp
from rca_connector_mqtt.uns_service import UnsService

BROKER = os.environ.get("MQTT_SIM_BROKER", "127.0.0.1:1883")
HOST, _, _port = BROKER.partition(":")
PORT = int(_port or 1883)
GROUP = "SITE-DEMO"
DEVICE = "P-101A"
METRIC = "discharge_pressure"


def _broker_reachable() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _broker_reachable(),
    reason=f"MQTT broker not reachable at {BROKER} (run `task parity:mqtt`)",
)


async def _wait_for(predicate, *, timeout: float = 15.0, interval: float = 0.5) -> bool:
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        waited += interval
    return predicate()


async def test_connector_decodes_live_uns_stream():
    state = SubscriptionState()
    svc = UnsService(broker_host=HOST, broker_port=PORT, state=state, group_id=GROUP,
                     client_id="rca-uns-parity")
    svc.start()
    try:
        # retained BIRTH teaches aliases; DDATA fills values within a couple of ticks.
        got = await _wait_for(lambda: state.current_values.get(f"{DEVICE}/{METRIC}") is not None)
        assert got, "no live UNS value arrived for the test metric"

        mcp = make_mqtt_mcp(state=state)
        async with McpClient(mcp) as client:
            res = await client.call_tool("uns.browse_namespace", {"request": {}})
            payload = res.structured_content if res.structured_content is not None else res.data
            tree = ToolResponse[NamespaceTree].model_validate_json(json.dumps(payload))
            assert tree.error is None, tree.error
            assert tree.data.group_id == GROUP
            dev = next(d for d in tree.data.devices if d.device_id == DEVICE)
            dp = next(m for m in dev.metrics if m.name == METRIC)
            assert isinstance(dp.value, float) and dp.alias is not None
            assert f"{DEVICE}/{METRIC}" in tree.provenance.raw_tags

            res = await client.call_tool(
                "uns.get_recent_messages", {"request": {"device_id": DEVICE, "limit": 20}}
            )
            payload = res.structured_content if res.structured_content is not None else res.data
            recent = ToolResponse[RecentMessages].model_validate_json(json.dumps(payload))
            assert recent.error is None, recent.error
            assert recent.data.messages, "expected recent UNS messages for the device"
            assert all(m.device_id == DEVICE for m in recent.data.messages)
            assert recent.data.messages[-1].timestamp.tzinfo is not None
    finally:
        svc.stop()
