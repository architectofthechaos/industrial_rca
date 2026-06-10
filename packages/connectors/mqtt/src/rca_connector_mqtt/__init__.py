"""rca_connector_mqtt — MQTT/UNS connector (S13.7).

Background-ingest shape: a paho Sparkplug B subscriber (`UnsService` in `uns_service`)
keeps a `SubscriptionState` cache fresh; the FastMCP read tools (`uns.browse_namespace`,
`uns.get_recent_messages`, built by `make_mqtt_mcp` in `server`) serve canonical views of
that cache. Never imports rca_simulator (ADR-0012) — it owns its own Sparkplug B codec
(`sparkplug`). Import from the submodules (`.server`, `.uns_service`), matching the other
connectors' convention.
"""
