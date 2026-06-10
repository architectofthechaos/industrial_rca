"""S2.5 — OPC UA server integration tests (real asyncua server + client, loopback).

Boots the simulator on a loopback endpoint, then connects an OPC UA client to
browse the hierarchy and read current values that track the active scenario.
"""
import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from asyncua import Client, ua

from rca_simulator.fixtures.loader import load
from rca_simulator.fixtures.scenario_expander import value_at
from rca_simulator.opcua.server import OpcUaSimulator

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
SCENARIO = "seal_leak_progression"
ENDPOINT = "opc.tcp://127.0.0.1:48401"
NS_URI = "urn:rca:sim:refplant"


async def _started_sim():
    rp = load(REFPLANT)
    sim = OpcUaSimulator(rp, SCENARIO, endpoint=ENDPOINT, namespace_uri=NS_URI)
    await sim.start()
    return rp, sim


async def test_client_reads_current_value_matching_expander():
    rp, sim = await _started_sim()
    try:
        t = rp.scenarios[SCENARIO].t0 + timedelta(days=10)
        await sim.update_once(t)
        async with Client(ENDPOINT) as client:
            idx = await client.get_namespace_index(NS_URI)
            node = client.get_node(ua.NodeId("P-101A.discharge_pressure", idx))
            val = await node.read_value()
        assert val == pytest.approx(
            value_at(rp, SCENARIO, "P-101A.discharge_pressure", t)
        )
    finally:
        await sim.stop()


async def test_values_track_scenario_over_time():
    rp, sim = await _started_sim()
    try:
        t0 = rp.scenarios[SCENARIO].t0
        async with Client(ENDPOINT) as client:
            idx = await client.get_namespace_index(NS_URI)
            node = client.get_node(ua.NodeId("P-101A.discharge_pressure", idx))

            await sim.update_once(t0 + timedelta(days=1))
            early = await node.read_value()
            await sim.update_once(t0 + timedelta(days=29))
            late = await node.read_value()
        # seal-leak decays discharge pressure ~180 kPa; noise (~35) can't mask it
        assert late < early - 100
    finally:
        await sim.stop()


async def test_client_can_subscribe_to_value_changes():
    rp, sim = await _started_sim()
    try:
        received: list[float] = []

        class Handler:
            def datachange_notification(self, node, val, data):
                received.append(val)

        t0 = rp.scenarios[SCENARIO].t0
        async with Client(ENDPOINT) as client:
            idx = await client.get_namespace_index(NS_URI)
            node = client.get_node(ua.NodeId("P-101A.discharge_pressure", idx))
            sub = await client.create_subscription(100, Handler())
            await sub.subscribe_data_change(node)
            await asyncio.sleep(0.3)                       # initial value notification
            await sim.update_once(t0 + timedelta(days=10))  # change -> notification
            await asyncio.sleep(0.3)
            await sim.update_once(t0 + timedelta(days=20))  # change -> notification
            await asyncio.sleep(0.3)
            await sub.delete()
        assert len(received) >= 2                          # initial + at least one change
    finally:
        await sim.stop()


async def test_client_can_browse_plant_hierarchy():
    _rp, sim = await _started_sim()
    try:
        async with Client(ENDPOINT) as client:
            children = await client.nodes.objects.get_children()
            names = [(await c.read_browse_name()).Name for c in children]
        assert "SITE-DEMO" in names
    finally:
        await sim.stop()
