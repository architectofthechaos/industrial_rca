"""S2.5 — OPC UA simulator (real asyncua server).

Mirrors the reference-plant hierarchy as an OPC UA address space and serves
current values for every signal, driven by the scenario expander. This is the
real-time TRIGGER source (historical evidence is PI, S2.2). Updates at ~1 Hz.

The address-space *plan* is pure (``address_space.build_node_plan``); this module
materializes it on an ``asyncua`` server and writes values via ``value_at``.
Realism (clock skew, bad quality) is applied via the shared S2.8 harness.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from asyncua import Server, ua

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import value_at
from ..realism.inject import RealismInjector
from .address_space import build_node_plan

logging.getLogger("asyncua").setLevel(logging.ERROR)  # keep test output pristine


class OpcUaSimulator:
    def __init__(
        self,
        rp: RefPlant,
        scenario_id: str,
        *,
        endpoint: str = "opc.tcp://0.0.0.0:4840",
        namespace_uri: str = "urn:rca:sim:refplant",
        seed: int = 0,
        realism: RealismInjector | None = None,
    ) -> None:
        self.rp = rp
        self.scenario_id = scenario_id
        self.endpoint = endpoint
        self.namespace_uri = namespace_uri
        self.seed = seed
        self.realism = realism
        self._server: Server | None = None
        self._idx: int = 0
        self._var_nodes: dict[str, object] = {}   # signal_key -> Variable node

    async def start(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        self._idx = await server.register_namespace(self.namespace_uri)

        folders: dict[tuple[str, ...], object] = {}
        for plan in build_node_plan(self.rp):
            parent = server.nodes.objects
            # ensure Site/Area/Unit/Asset folders exist along the browse path
            for depth in range(1, len(plan.browse_path)):
                path = plan.browse_path[:depth]
                if path not in folders:
                    name = path[-1]
                    folders[path] = await parent.add_folder(
                        ua.NodeId(f"folder:{'/'.join(path)}", self._idx), name
                    )
                parent = folders[path]
            # the leaf variable (a signal) under its asset folder
            role = plan.browse_path[-1]
            var = await parent.add_variable(
                ua.NodeId(plan.identifier, self._idx),
                role,
                ua.Variant(0.0, ua.VariantType.Double),
            )
            self._var_nodes[plan.signal_key] = var

        self._server = server
        await server.start()

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop()
            self._server = None

    async def update_once(self, t: datetime) -> None:
        """Write every signal's current value at scenario time ``t``."""
        for signal_key, node in self._var_nodes.items():
            value = value_at(self.rp, self.scenario_id, signal_key, t, seed=self.seed)
            await node.write_value(ua.Variant(value, ua.VariantType.Double))  # type: ignore[attr-defined]

    async def run(self, t0: datetime, step_seconds: float = 1.0) -> None:
        """Advance scenario time from ``t0`` at 1 Hz, writing values each tick."""
        t = t0
        while True:
            await self.update_once(t)
            await asyncio.sleep(step_seconds)
            t += timedelta(seconds=step_seconds)


async def main() -> None:
    """CLI entrypoint for the Docker image: serve the scenario in real time."""
    import os

    from ..fixtures.loader import load
    from ..realism.config import RealismConfig

    rp = load(os.environ.get("FIXTURE_PATH", "fixtures/refplant"))
    scenario = os.environ.get("SCENARIO", "seal_leak_progression")
    endpoint = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840")
    sim = OpcUaSimulator(
        rp, scenario, endpoint=endpoint,
        realism=RealismInjector(RealismConfig.from_env()),
    )
    await sim.start()
    try:
        await sim.run(rp.scenarios[scenario].t0)
    finally:
        await sim.stop()


if __name__ == "__main__":
    asyncio.run(main())


__all__ = ["OpcUaSimulator", "main"]
