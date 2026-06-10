# PI Historian Simulator (S2.2)

Stands in for **OSIsoft / AVEVA PI** via a subset of the **PI Web API REST** interface.
This is the source of **historical evidence** (real-time triggers come from OPC UA / MQTT).

## Run
| | |
|---|---|
| Docker | `task up:pi` → `http://localhost:8001` |
| Local  | `task run:pi` (foreground, `:8001`) |

Container listens on `:8000`, published to host `:8001`. Active scenario defaults to
`seal_leak_progression` (env `SCENARIO`); affected asset shows the anomaly, others stay at baseline.

## Addressing streams (WebID)
A stream is addressed by a **WebID** — a reversible base64 of the fixture signal key `"<tag>.<role>"`:
```bash
uv run python -c "from rca_simulator.pi.webid import encode_webid; print(encode_webid('P-101A.discharge_pressure'))"
```
Signals per pump (`P-101A`, `P-101B`, `P-102A`, `P-103A`): `discharge_pressure`, `suction_pressure`,
`motor_amps`, `vibration_radial`, `bearing_temp_de`; `P-101A` also has `seal_flush_flow`.

## Endpoints
| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/streams/{webId}/recorded` | `startTime`, `endTime` | stored points (compression-filtered, event-driven) |
| GET | `/streams/{webId}/interpolated` | `startTime`, `endTime`, `interval` (`60s`, `1m`) | regular grid; each item `IsInterpolated: true` |
| GET | `/streams/{webId}/summary` | `startTime`, `endTime`, `summaryType` (`Average`/`Minimum`/`Maximum`/`Total`), `summaryDuration` (`15m`) | aggregates per interval |
| GET | `/eventframes` | `startTime`, `endTime` | scenario alarms as PI event frames |
| GET | `/assetdatabases` | — | list of AF databases (always one: `Refinery-GC`) |
| GET | `/assetdatabases/{webId}` | — | single AF database by WebID |
| GET | `/assetdatabases/{webId}/elements` | `nameFilter`, `searchFullHierarchy`, `maxCount` | root elements of the database (the site node) |
| GET | `/elements/{webId}` | — | single AF element by WebID |
| GET | `/elements/{webId}/elements` | `nameFilter`, `searchFullHierarchy`, `maxCount` | direct children (or full subtree) of an element |
| GET | `/elements/{webId}/attributes` | — | flat `{WebId, Name, Value}` list of asset nameplate attributes |

Times are **absolute ISO-8601 UTC** (`2026-03-06T00:00:00Z`). Relative PI syntax (`*-1d`) is not supported.
OpenAPI docs: `http://localhost:8001/docs`.

## AF WebIDs
AF WebIDs deterministically encode the synthesized AF path
(`\\{AFServer}\{Database}\{Element}\...`) using the same URL-safe base64 scheme
as stream WebIDs. Stream WebIDs encode `tag.role` keys (e.g.
`P-101A.discharge_pressure`); element WebIDs encode `\\PI-DEMO\...` paths — the
two namespaces cannot collide even though they share the codec.

### Sprint-1 deviations
- **Negative `maxCount`** is clamped to an empty result rather than returning
  HTTP 400 as real PI Web API does.
- **404 bodies** use FastAPI's `{"detail": "..."}` shape rather than PI's
  `{"Errors": [...]}` envelope.

## Example
```bash
WID=$(uv run python -c "from rca_simulator.pi.webid import encode_webid; print(encode_webid('P-101A.discharge_pressure'))")
curl "http://localhost:8001/streams/$WID/recorded?startTime=2026-03-06T00:00:00Z&endTime=2026-03-06T00:01:00Z"
```
```json
{"Items":[{"Timestamp":"2026-03-06T00:00:00Z","Value":1345.39,"Good":true,"Questionable":false,"Substituted":false}]}
```

## Notes
- `recorded` vs `interpolated` vs `aggregated` return materially different, mode-correct responses.
- Values are the synthesized magnitude labeled with the source's **raw** unit; canonical-unit
  conversion is the connector's job and is intentionally not done here.
- Realism (clock skew / bad-quality) is configured via `SIM_*` env vars (off by default).
