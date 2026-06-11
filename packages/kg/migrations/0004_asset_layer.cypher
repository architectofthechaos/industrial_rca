// 0004_asset_layer — lazy KG Asset layer + warm-layer failure events (Sprint 3 WI4/WI6).
// Asset nodes are materialized first-touch on a probe (kg.upsert_asset); HistoricalFailureEvent
// + WorkOrder are written by the close phase (WI6). Per-label uniqueness on id (mirrors 0001);
// Asset lookup indexes on plant_id / unit_slug / iso14224_class for kg.get_asset_context's
// class-level prior-event query. WorkOrder here is the *referenced* node for the RESULTED_IN
// edge (G21) — not the read-side work_order MCP (that stays vendor data over HTTP).

CREATE CONSTRAINT asset_id IF NOT EXISTS FOR (n:Asset) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT historical_failure_event_id IF NOT EXISTS FOR (n:HistoricalFailureEvent) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT work_order_id IF NOT EXISTS FOR (n:WorkOrder) REQUIRE n.id IS UNIQUE;

CREATE INDEX asset_plant_id IF NOT EXISTS FOR (n:Asset) ON (n.plant_id);
CREATE INDEX asset_unit_slug IF NOT EXISTS FOR (n:Asset) ON (n.unit_slug);
CREATE INDEX asset_iso14224_class IF NOT EXISTS FOR (n:Asset) ON (n.iso14224_class);
CREATE INDEX historical_failure_event_canonical IF NOT EXISTS FOR (n:HistoricalFailureEvent) ON (n.canonical_id);
