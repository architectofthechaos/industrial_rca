"""rca_simulator — source-side simulators for the RCA MVP (EPIC-002, Track B).

Each subpackage stands in for a real upstream SOURCE system and speaks that
system's native protocol. Simulators do NOT expose MCP and do NOT import any
product code (packages/contracts, MAR, TRS, connector_sdk). See ADR-0012.

Subpackages
-----------
fixtures   S2.1  Shared fixture schema, loader, scenario expander, validator.
                 Single source of truth read by every simulator. BLOCKS the rest.
realism    S2.8  Shared realism-injection harness (skew/drop/latency/5xx/quality).
                 Imported by every simulator. Parallel to fixtures.
pi         S2.2  PI Historian        — PI Web API REST subset.
maximo     S2.3  Maximo              — OSLC REST.
sap_pm     S2.4  SAP PM             — OData v2 (CSRF dance).
opcua      S2.5  OPC UA             — real asyncua server (opc.tcp://...).
documents  S2.6  SharePoint / S3    — Graph + Search REST (MinIO variant).
mqtt       S2.7  MQTT Sparkplug B   — real broker + publisher.
"""
