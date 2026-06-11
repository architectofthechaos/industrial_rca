"""rca_connector_documents — the SharePoint-backed ``document`` entity MCP (Sprint 2b Track 3).

Translates SharePoint/Graph (HTTP) document sources into the canonical DocumentRef contract
and serves them as the ``document`` entity MCP (search_for_asset / get / list_by_type),
routing per request via the connection registry. Replaces the old documents.* vendor tools.
Product code: never imports rca_simulator.
"""
