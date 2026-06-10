"""S2.5 — OPC UA simulator (real asyncua server).

A real OPC UA server on opc.tcp://localhost:4840 mirroring the plant hierarchy
as an address space, serving 1 Hz current values driven by the scenario expander.
This is the REAL-TIME trigger source (not historical evidence — that is PI).

Modules
-------
server.py         asyncua server, address-space build, 1 Hz updater. Realism via harness.
address_space.py  fixture plant/asset/signal hierarchy -> OPC UA nodes;
                  deterministic NodeId / browse-path <-> fixture-signal mapping.
Dockerfile        Container image.

Ref: SPEC-007 (OPC UA section), TASK-S2.5.
"""
