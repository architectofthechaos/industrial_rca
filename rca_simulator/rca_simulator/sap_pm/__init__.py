"""S2.4 — SAP PM simulator (SAP OData v2 notifications).

Stands in for SAP PM. Models the same shared assets as Maximo but with different
field names and coding schemes, so the connector's normalization / dedup path is
exercised. Implements the full CSRF token dance.

Modules
-------
app.py      FastAPI OData v2 routes (/sap/opu/odata/sap/PM_NOTIFICATION_SRV)
            + X-CSRF-Token: Fetch handshake before writes.
odata.py    $metadata, $filter/$expand/$select parsing, entity serialization
            with SAP namespace prefixes.
seed.py     scenario -> notifications using SAP field naming.
Dockerfile  Container image.

Ref: SPEC-007 (SAP PM section), TASK-S2.4.
"""
