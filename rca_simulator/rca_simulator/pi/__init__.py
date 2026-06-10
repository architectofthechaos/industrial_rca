"""S2.2 — PI Historian simulator (PI Web API REST subset).

Stands in for a PI server. Synthesizes time series on demand from the fixture.
Source of HISTORICAL evidence (real-time triggers come from OPC UA / MQTT).

Modules
-------
app.py           FastAPI routes: /streams/{webId}/recorded, /interpolated,
                 /summary, /eventframes, plus the AF hierarchy surface
                 (/assetdatabases, /elements). Wraps responses in the realism
                 harness (defaults: skew +/-2s, 1% dropped intervals, 0.5%
                 bad-quality).
af_hierarchy.py  AF element index (AfIndex, AfDatabase, AfElement) built once at
                 app construction from the fixture plant tree; ``select()``
                 implements PI element-list filter/truncate semantics.
webid.py         WebID encode/decode <-> fixture signals.
synthesize.py    Series synthesis + PI `mode` semantics:
                 stored (compression-deviation crossings only) /
                 interpolated (is_interpolated flagged) / aggregated (true aggregates).
Dockerfile       Container image.

Ref: SPEC-007 (PI section), TASK-S2.2.
"""
