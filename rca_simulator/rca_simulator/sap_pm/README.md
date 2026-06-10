# SAP PM Simulator (S2.4)

Stands in for **SAP Plant Maintenance** via an **OData v2** notification service. Models the
same assets as Maximo but with different field names/codes — so the connector's normalization
and cross-source dedup are exercised.

## Run
| | |
|---|---|
| Docker | `task up:sap` → `http://localhost:8003` |
| Local  | `task run:sap` (foreground, `:8003`) |

Service root: `/sap/opu/odata/sap/PM_NOTIFICATION_SRV`

## Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET  | `…/$metadata` | EDMX metadata (namespace `RCA.PM`, `NotificationSet`) |
| GET  | `…/NotificationSet` | notifications (OData v2 envelope) |
| POST | `…/NotificationSet` | create a notification (**CSRF-protected**, idempotent by `QMNUM`) |

**Query options:** `$filter` (e.g. `EQUNR eq '10001234'`, ops `eq ne gt lt ge le`, joined by `and`), `$select` (`QMNUM,EQUNR`).

**Envelope:** `{"d": {"results": [ {...} ]}}`
**Fields:** `QMNUM` (notification no.), `EQUNR` (equipment no.), `QMTXT` (text), `QMART` (type),
`PRIOK` (priority), `FECOD` (failure code), `AUSVN` (date `yyyymmdd`).

## CSRF token dance (required for writes)
```bash
BASE=http://localhost:8003/sap/opu/odata/sap/PM_NOTIFICATION_SRV
# 1. fetch a token (header comes back on any GET with X-CSRF-Token: Fetch)
TOKEN=$(curl -s -D - -o /dev/null "$BASE/NotificationSet" -H 'X-CSRF-Token: Fetch' \
        | awk 'tolower($1)=="x-csrf-token:"{print $2}' | tr -d '\r')
# 2. write with the token (omitting/expiring it -> 403)
curl -X POST "$BASE/NotificationSet" -H "X-CSRF-Token: $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"QMNUM":"90000001","EQUNR":"10001234","QMTXT":"new notification"}'
```

## Notes
- Only a **subset** of the plant is on SAP (`SAP_ASSETS = {P-101A, P-103A}`); `P-101A` overlaps Maximo,
  so the same seal-leak event appears here under SAP's schema (`EQUNR 10001234`, `FECOD 0010`).
- Asset ↔ `EQUNR` mapping comes from each asset's `external_ids.sap_equipment` in the fixture.
