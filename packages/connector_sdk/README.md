# rca_connector_sdk

Shared platform every connector imports: Pydantic validation, provenance stamping,
unit/time normalization, retry, error mapping, the FastMCP skeleton — and the
uniform **health-check contract** documented here. Connectors implement source
fetch + translate; the SDK owns everything cross-cutting. Product code never
imports `rca_simulator` (ADR-0012).

## Health-check contract (`rca_connector_sdk.health`)

Every **live connector** (pi, maximo, documents, asset_hierarchy, opc_ua, mqtt —
not sap_pm, not echo, and not the MAR/KG registries) exposes the same two ops
surfaces, registered by `register_health(mcp, *, version=..., probe=...)` inside
its `make_*_mcp` factory.

### 1. `GET /health` (custom HTTP route)

Probes the *configured* upstream (`base_url=None`) with a 5-second budget and
returns a `HealthReport`:

```json
{
  "status": "healthy | degraded | unhealthy",
  "checks": [
    {"name": "reachability", "status": "pass | fail | skip",
     "latency_ms": 12.3, "message": "optional detail"}
  ],
  "version": "0.1.0"
}
```

HTTP status: **200** for `healthy`/`degraded`, **503** for `unhealthy`. If the
probe itself raises, the route reports `unhealthy` with a single synthetic
`probe` fail check (still 503). The route is part of the FastMCP HTTP app
(`mcp.http_app()`), mounted at the root next to the MCP endpoint.

### 2. `test_connection` (MCP tool)

An ops tool for the Connections page — deliberately **not** ToolResponse-wrapped
(no provenance envelope; the spec fixes its exact shape).

Request (`TestConnectionRequest`):

```json
{"base_url": "http://other-host:8001", "timeout_seconds": 5.0}
```

`base_url` is optional and overrides the connector's configured upstream for a
one-off test (e.g. validating a new connection before saving it). Response
(`TestConnectionResponse`):

```json
{
  "success": true,
  "checks": [...same CheckResult shape as /health...],
  "upstream_version": "0.1.0",
  "error_summary": null
}
```

* `success` = no check failed (`skip` does not fail a test).
* `upstream_version` is harvested when discoverable (HTTP sources read
  `info.version` from `{base}/openapi.json`).
* `error_summary` joins the failing checks as `"name: message; ..."`; if the
  probe raises before producing checks, `success=false`, `checks=[]`, and
  `error_summary` carries the exception text.

### Aggregation semantics — the first check is the gate

Probes return their checks **with the connectivity gate first**. `aggregate`:

| condition                  | status      |
|----------------------------|-------------|
| no `fail` anywhere         | `healthy`   |
| first check failed         | `unhealthy` |
| any other check failed     | `degraded`  |

`skip` never degrades. By convention, when the gate fails the remaining checks
are emitted as `skip` ("skipped: <gate> failed") so a dead host does not pay one
timeout per sub-check and the documented check names stay present.

### Sub-check menu per connector family

| family | gate (first check) | follow-up checks |
|---|---|---|
| HTTP-based (pi, maximo, documents, asset_hierarchy) | `reachability` — GET `{base}/openapi.json`, harvest `info.version` | `auth` (skip while no credentials are configured — MVP), then one or more cheap `schema:*` reads (pi: `schema:af` `/assetdatabases` + `schema:historian` `/eventframes?…1-minute window`; maximo: `schema:workorders` `/maxrest/oslc/os/mxwo?oslc.pageSize=1`; documents: `schema:search` `/search?q=health&top=1`; asset_hierarchy: `schema:assetdatabases` `/assetdatabases`) |
| MQTT (mqtt/UNS) | `broker_connect` — paho connect + CONNACK | `subscribe` — SUBACK on `spBv1.0/#` |
| OPC UA | `endpoint_reachability` — TCP connect to the host:port of the `opc.tcp://` endpoint | `session` — asyncua `Client(url).connect()` + disconnect |

### Wiring a connector

```python
from rca_connector_sdk import register_health

def make_my_mcp(*, http_client: httpx.AsyncClient, ...) -> FastMCP:
    mcp = build_server("my-connector")
    ...  # register the evidence tools
    register_health(mcp, version=_VERSION, probe=MyHealthProbe(client_factory))
    return mcp
```

A probe satisfies the `HealthProbe` protocol —
`async def run(self, base_url: str | None, timeout: float) -> ProbeResult` where
`ProbeResult = tuple[list[CheckResult], str | None]` (checks + optional upstream
version). Build sub-checks with `timed_check(name, coro_factory)` (latency via
`perf_counter`; exceptions become `fail` with `"ExcType: text"`) and
`skipped_check(name, message)`. HTTP probes take a **client factory**
`Callable[[str | None, float], httpx.AsyncClient]` so hermetic tests can inject
ASGI-backed clients; the default factory builds a fresh client from the
connector's configured base_url or the per-request override. Connectors whose
upstream is per-request (asset_hierarchy) accept a `default_base_url` factory
kwarg and fail the probe gracefully ("no base_url configured; pass base_url")
when neither it nor the request provides one.
