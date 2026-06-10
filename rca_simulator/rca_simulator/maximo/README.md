# Maximo Simulator (S2.3)

Stands in for **IBM Maximo** via a subset of the **Maximo OSLC REST** interface.

## Run
| | |
|---|---|
| Docker | `task up:maximo` → `http://localhost:8002` |
| Local  | `task run:maximo` (foreground, `:8002`) |

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET  | `/maxrest/oslc/os/mxwo` | work orders |
| POST | `/maxrest/oslc/os/mxwo` | create/update a work order (idempotent by `wonum`) |
| GET  | `/maxrest/oslc/os/mxsr` | service requests |
| GET  | `/maxrest/oslc/os/mxfailrep` | failure reports |

**Query options** (on the GET endpoints):
- `oslc.where` — e.g. `location="CRDU-P101A"`, `status="COMP" and reportdate>="2026-03-01"` (ops: `= != > < >= <=`, joined by `and`)
- `oslc.select` — comma-separated projection, e.g. `wonum,status`
- `oslc.pageSize` + `oslc.pageNo` — paging (1-based)

**Response shape:** `{"member": [ {...} ], "responseInfo": {"totalCount": N}}`

Work-order fields: `wonum`, `location`, `description`, `status`, `reportdate`, `worktype`,
`wopriority`, `problemcode`, `failurecode`, `siteid`.

## Examples
```bash
# seal-leak work orders for P-101A
curl 'http://localhost:8002/maxrest/oslc/os/mxwo?oslc.where=location%3D%22CRDU-P101A%22'

# idempotent write-back
curl -X POST http://localhost:8002/maxrest/oslc/os/mxwo \
  -H 'Content-Type: application/json' \
  -d '{"wonum":"WO-99999001","location":"CRDU-P101A","description":"new","status":"WAPPR"}'
```

## Notes
- `reportdate` is **local time without timezone** (e.g. `2026-03-18T19:00:00`) to exercise connector normalization.
- At least one failure report carries a **legacy (non-ISO-14224) code** (`SEAL-LEG-07`) alongside ISO codes (`LEK`, `VIB`).
- Asset ↔ Maximo location mapping comes from each asset's `external_ids.maximo_location` in the fixture.
- Occasional `5xx` can be injected via `SIM_5XX_RATE` (off by default).
