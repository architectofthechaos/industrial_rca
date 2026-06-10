# OPC UA Simulator (S2.5)

A **real OPC UA server** (`asyncua`) mirroring the plant hierarchy as an address space and
serving current values that update at **~1 Hz**. This is the **real-time trigger** source
(historical evidence is PI, S2.2).

## Run
| | |
|---|---|
| Docker | `task up:opcua` → `opc.tcp://localhost:4840` |
| Local  | `task run:opcua` (foreground, `:4840`) |

## Connect
- **Endpoint:** `opc.tcp://localhost:4840`
- **Namespace URI:** `urn:rca:sim:refplant` (resolve the index with `get_namespace_index`)
- **NodeId:** string identifier = the signal key `"<tag>.<role>"`, e.g. `ns=<idx>;s=P-101A.discharge_pressure`
- **Browse path:** `Objects → <SITE> → <AREA> → <UNIT> → <ASSET> → <role>` (e.g. `SITE-DEMO/AREA-100/UNIT-101/P-101A/discharge_pressure`)

```python
import asyncio
from asyncua import Client, ua

async def main():
    async with Client("opc.tcp://localhost:4840") as c:
        idx = await c.get_namespace_index("urn:rca:sim:refplant")
        node = c.get_node(ua.NodeId("P-101A.discharge_pressure", idx))
        print("value:", await node.read_value())          # current value
        # subscribe for 1 Hz updates
        class H:
            def datachange_notification(self, n, v, d): print("update:", v)
        sub = await c.create_subscription(500, H())
        await sub.subscribe_data_change(node)
        await asyncio.sleep(3)
        await sub.delete()

asyncio.run(main())
```

CLI sanity check: any OPC UA client (e.g. `opcua-client` GUI, UaExpert) can connect to
`opc.tcp://localhost:4840` and browse the tree.

## Notes
- Active scenario defaults to `seal_leak_progression`; subscribed values track the scenario in real time.
- Values are doubles in the signal's synthesized magnitude (raw-unit conversion is the connector's job).
- Clock skew / bad quality can be injected via `SIM_*` env vars (off by default).
