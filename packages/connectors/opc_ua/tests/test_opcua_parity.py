"""S13.8 parity: OPC UA connector against the REAL EPIC-002 OPC UA simulator.

Connects via asyncua to opc.tcp://127.0.0.1:4840 (native protocol; never imports
rca_simulator). Skips when the sim is down. Run with: `task parity:opcua`.
"""
import asyncio
import json
import os
from uuid import uuid4

import pytest
from asyncua import Client
from fastmcp import Client as McpClient
from rca_connector_sdk import SourceBinding, SubscriptionState
from rca_contracts import Measurement, PressureReference, SignalDescriptor, ToolResponse

from rca_connector_opc_ua.server import make_opcua_mcp
from rca_connector_opc_ua.subscription import OpcUaSubscription

ENDPOINT = os.environ.get("OPCUA_SIM_URL", "opc.tcp://127.0.0.1:4840")
NS = "urn:rca:sim:refplant"
HANDLE = "P-101A.discharge_pressure"
SID = uuid4()


def _sim_reachable() -> bool:
    async def _try() -> bool:
        try:
            async with Client(ENDPOINT) as c:
                await c.get_namespace_index(NS)
            return True
        except Exception:
            return False
    try:
        return asyncio.run(_try())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _sim_reachable(), reason=f"OPC UA simulator not reachable at {ENDPOINT} (run `task parity:opcua`)"
)


def _signal() -> SignalDescriptor:
    return SignalDescriptor(
        signal_id=SID, tenant_id=uuid4(), asset_id=uuid4(),
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.gauge,
    )


def _parse(result) -> "ToolResponse[Measurement]":
    payload = result.structured_content if result.structured_content is not None else result.data
    return ToolResponse[Measurement].model_validate_json(json.dumps(payload))


async def test_get_current_value_against_real_simulator():
    signals = {SID: _signal()}
    bindings = {(SID, "opc_ua"): SourceBinding(handle=HANDLE, raw_unit="psig")}
    mcp = make_opcua_mcp(endpoint=ENDPOINT, namespace_uri=NS, signals=signals, bindings=bindings)
    async with McpClient(mcp) as client:
        res = await client.call_tool("opc_ua.get_current_values", {"request": {"signal_id": str(SID)}})
        resp = _parse(res)
        assert resp.error is None, resp.error
        assert resp.data is not None and isinstance(resp.data.value, float)
        assert resp.data.timestamp.tzinfo is not None
        assert resp.provenance.record_count == 1
        assert HANDLE in resp.provenance.raw_tags


async def test_background_subscription_populates_cache():
    state = SubscriptionState()
    sub = OpcUaSubscription(endpoint=ENDPOINT, namespace_uri=NS, handles=[HANDLE], state=state)
    stop = asyncio.Event()
    task = asyncio.create_task(sub.run(stop))
    try:
        for _ in range(20):                      # wait up to ~10s for a data-change notification
            if HANDLE in state.current_values:
                break
            await asyncio.sleep(0.5)
        assert HANDLE in state.current_values    # live subscription filled the cache
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=5)
