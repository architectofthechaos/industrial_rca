# MQTT Sparkplug B Simulator (S2.7)

A **real MQTT broker** (Mosquitto) plus a **Sparkplug B publisher** that emits the whole plant as a
UNS feed. One Sparkplug *device* per asset, one *metric* per signal. An authoritative source for
TRS alias ingestion.

## Run
| | |
|---|---|
| Docker | `task up:mqtt` → broker on `localhost:1883` + publisher |
| Local  | `task broker:up` then `task run:mqtt` (publisher needs a broker) |

## Topic namespace
```
spBv1.0/{group_id}/{message_type}/{edge_node_id}[/{device_id}]
```
- `group_id` = `SITE-DEMO`, `edge_node_id` = `UNS-EDGE-1`, `device_id` = asset tag (`P-101A`, …)
- `NBIRTH` / `DBIRTH` — **retained**; declare metric **names + aliases** (so a subscriber joining mid-stream can decode)
- `DDATA` — published ~1 Hz, **alias-only** metrics (resolve names via the device's DBIRTH), `seq` increments 0–255 wrapping

Payloads are **Sparkplug B protobuf** (Eclipse Tahu field numbers).

## Connect
```bash
# raw frames
mosquitto_sub -h localhost -t 'spBv1.0/#' -v
```
```python
import paho.mqtt.client as mqtt
from rca_simulator.mqtt.sparkplug import decode_payload

births = {}                       # alias -> name, per device
def on_message(c, u, m):
    payload = decode_payload(m.payload)
    if "/DBIRTH/" in m.topic:
        dev = m.topic.split("/")[-1]
        births[dev] = {mt.alias: mt.name for mt in payload.metrics}
    elif "/DDATA/" in m.topic:
        dev = m.topic.split("/")[-1]
        names = births.get(dev, {})
        print(dev, {names.get(mt.alias): mt.value for mt in payload.metrics})

cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
cli.on_message = on_message
cli.connect("localhost", 1883)
cli.subscribe("spBv1.0/#")        # retained BIRTH arrive immediately
cli.loop_forever()
```

## Notes
- Active scenario defaults to `seal_leak_progression`; DDATA values track the scenario; non-affected assets stay at baseline.
- Values are doubles in the signal's synthesized magnitude (raw-unit conversion is the connector's job).
- Drops / clock skew can be injected via `SIM_*` env vars (off by default).
