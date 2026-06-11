# Entity MCP Topology

Phase 1 exposes the data layer as **one MCP server per canonical entity category**
(spec §7.1). Callers — internal UI code, the onboarding pipeline, the simulators, and
(later) AI agents — only ever speak the entity vocabulary; vendor names never appear in a
tool name (spec §7.2, the hard naming rule).

## The six entity MCP servers

| Entity MCP        | Server name      | Backed by (store / connector)        | Factory                  | Tools |
| ----------------- | ---------------- | ------------------------------------ | ------------------------ | ----- |
| **Asset**         | `asset`          | MAR registry (+ KG hierarchy)        | `make_mar_mcp`           | `asset.resolve`, `asset.get`, `asset.search` |
| **Tag**           | `tag`            | Historian connector (PI Historian)   | `make_tag_mcp`           | `tag.list_for_asset`, `tag.get_history`, `tag.get_current`, `tag.get_metadata` |
| **Work Order**    | `work_order`     | CMMS connector (Maximo)              | `make_work_order_mcp`    | `work_order.list_for_asset`, `work_order.get`, `work_order.list_recent` |
| **Document**      | `document`       | Document Repository connector (SharePoint) | `make_document_mcp` | `document.search_for_asset`, `document.get`, `document.list_by_type` |
| **Operator Log**  | `operator_log`   | Operator Logs connector (PI Event Frames) | `make_operator_log_mcp` | `operator_log.list_for_asset`, `operator_log.get` |
| **KG**            | `kg`             | Knowledge graph (Neo4j)              | `make_kg_mcp`            | `kg.get_ontology_node`, `kg.list_failure_modes_for_class`, `kg.get_hierarchy`, `kg.find_path` |

Vendor names (PI, Maximo, SharePoint) describe what *backs* each server today — they are an
adapter-config detail, never part of the tool surface. Replacing PI Historian with IP.21
changes adapter config only, not any tool name or signature (spec §7.2). Provenance payloads
still carry the data `source` (e.g. `source="mar"`, `source="maximo"`) — that's the source of
the bytes, not a user-facing identifier.

## Single-process multi-mount (risk callout #5)

`scripts/run_mcp_host.py` mounts all six servers into ONE FastMCP process via
`FastMCP.mount(sub)` (fastmcp 3.4) and serves them on a single HTTP port (default `:8100`).
Each `make_*_mcp` factory already registers its tools under the entity vocabulary, and
mounting with **no prefix** preserves those names verbatim — so the host's surface is
byte-for-byte what the standalone servers expose (`asset.get`, `tag.list_for_asset`, …).

**Trade-off.** Co-locating the servers trades process isolation for operational simplicity:

- One port, one deploy unit, one lifecycle — simple for Phase 1 dev and the onboarding pipeline.
- But a single shared event loop / GIL: a hot or crashing tool can degrade or take down the
  whole host, and there is no per-entity resource isolation.
- The SDK health tool `test_connection` is registered by every connector-backed server, so
  the mount aggregate sees a duplicate-name component and keeps the first (a logged warning,
  not an error). Per-entity health is still reachable by running the servers standalone.

This is acceptable for Phase 1. Splitting back into per-entity processes is a **config change**
— each factory stands alone and is independently runnable — not a rewrite.

## Connection routing

Connector-backed servers (`tag`, `work_order`, `document`, `operator_log`) do not hard-code an
endpoint. Each request carries a `canonical_id`; the server:

1. Parses `plant_id` out of the `canonical_id` (`asset:{plant}:{unit}:{name}`).
2. Asks a `ConnectionRouter` for the **active connection** for `(plant_id, category)`.
   Phase 1 enforces *one source per category per plant* (spec §2 / §9), so this is
   unambiguous — exactly one `ConnectionInfo` matches.
3. Optionally honors a `connection_id` override on the request (wins over the active lookup;
   the future multi-source story rides on this seam).
4. Resolves the `canonical_id` to the source's vendor handle via an `AssetGateway`
   (historian tag, CMMS location, …) and calls the bound source at the connection's `base_url`.

The dev host wires a `StaticConnectionRouter` standing in for the Track-1 `connections`
registry (spec §4.4), with one connection per category pointing at the local simulators:

| Category       | connection_id                            | Dev base_url (sim)        |
| -------------- | ---------------------------------------- | ------------------------- |
| `historian`    | `refinery-gc.historian.pi-main`          | `http://127.0.0.1:8001`   |
| `operator_log` | `refinery-gc.operator_log.pi-event-frames` | `http://127.0.0.1:8001`  |
| `cmms`         | `refinery-gc.cmms.maximo-main`           | `http://127.0.0.1:8002`   |
| `document`     | `refinery-gc.document.sharepoint-main`   | `http://127.0.0.1:8004`   |

The PI historian and PI event-frames sims share one endpoint (`:8001`) but are distinct
categories, so each resolves to its own `ConnectionInfo`. The `asset` (MAR) and `kg` servers
read their own stores directly and need no router.

> Track-1 note: `asset.resolve` still takes a `source_system` request field. The
> `source_system → connection_id` rename is coupled to the connections migration and lands
> coherently in Track 1, not here. See the `# TODO(track1)` in `packages/mar/src/rca_mar/server.py`.

## Running

```bash
uv run python scripts/run_mcp_host.py            # serve on http://127.0.0.1:8100/mcp
uv run python scripts/run_mcp_host.py --check     # build + print the mounted tool surface, then exit
```

The `kg` server's Neo4j driver connects lazily (first tool call), so the host starts even
with Neo4j down; connector tools return a mapped `not_found` / `source_unavailable` if their
sim isn't reachable.
