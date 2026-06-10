"""rca_mar — Master Asset Registry (EPIC-012).

Canonical asset identity + 4-step resolution + read/resolve MCP tools, behind an
AssetRepository Protocol (in-memory + Postgres). Provides an in-process MarResolver
that satisfies connector_sdk's SignalResolver port for asset-scoped connectors.
Never imports rca_simulator (ADR-0012).
"""
__version__ = "0.0.1"
