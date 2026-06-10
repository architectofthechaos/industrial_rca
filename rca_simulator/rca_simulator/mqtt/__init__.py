"""S2.7 — MQTT Sparkplug B simulator (real broker + publisher).

A real MQTT broker (Mosquitto/EMQX) plus a publisher emitting Sparkplug B
payloads driven by the fixture. Authoritative source for TRS alias ingestion.

Modules
-------
publisher.py  On connect: NBIRTH/DBIRTH declaring tag metadata + aliases; then
              DATA at ~1 Hz with monotonic `seq`, values from the scenario expander.
sparkplug.py  Sparkplug B protobuf payload encode/decode helpers.
compose.yaml  Broker (Mosquitto/EMQX) for local dev.
Dockerfile    Publisher container image.

Ref: SPEC-007 (MQTT section), TASK-S2.7.
"""
