"""rca_connector_maximo — the Maximo-backed ``work_order`` entity MCP (Sprint 2b Track 3).

Translates Maximo OSLC REST work orders into the canonical WorkOrder contract and serves
them as the ``work_order`` entity MCP (list_for_asset / get / list_recent), routing per
request via the connection registry. Replaces the old maximo.* vendor tools. Product code:
never imports rca_simulator.
"""
