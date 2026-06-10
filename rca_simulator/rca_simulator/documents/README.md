# Document Simulator (S2.6)

Stands in for **SharePoint / Microsoft Graph** (and, optionally, **S3 / MinIO**), serving the
fixture documents: datasheets, a P&ID, and prior RCA reports — scenario-matched, some with
injected OCR noise.

## Run
| | |
|---|---|
| Docker | `task up:documents` → `http://localhost:8004` (MinIO via `task up:minio` → `:9000`, console `:9001`) |
| Local  | `task run:documents` (foreground, `:8004`) |

## HTTP endpoints (SharePoint / Graph)
| Method | Path | Purpose |
|---|---|---|
| GET | `/search?q=<text>&top=<n>` | ranked search (BM25 + lexical) |
| GET | `/drives/refplant/items/{id}` | drive-item metadata |
| GET | `/drives/refplant/items/{id}/content` | document bytes (OCR noise on scanned docs) |

**Search response:** `{"value": [ {"id","name","asset","docType","score","webUrl"} ]}`
**Document IDs:** `DS-P101A`, `DS-P101B`, `PID-U101` (scanned), `RCA-2025-014`, `RCA-2024-009`, `RCA-2023-022` (scanned).

```bash
curl 'http://localhost:8004/search?q=mechanical%20seal%20flush&top=3'
curl 'http://localhost:8004/drives/refplant/items/DS-P101A'
curl 'http://localhost:8004/drives/refplant/items/DS-P101A/content'
```

## S3 / MinIO variant (optional)
MinIO runs at `http://localhost:9000` (console `:9001`, creds `minioadmin`/`minioadmin`). Seed a
bucket from the fixtures, then read with any S3 client (`ListObjectsV2` / `GetObject`):
```python
from minio import Minio
from rca_simulator.documents.s3_variant import seed_bucket
c = Minio("localhost:9000", access_key="minioadmin", secret_key="minioadmin", secure=False)
seed_bucket(c, "refplant-docs", "fixtures/refplant/documents")   # keys: <doc_type>/<id>.pdf
print([o.object_name for o in c.list_objects("refplant-docs", recursive=True)])
```

## Notes
- Scanned docs (`PID-U101`, `RCA-2023-022`) are served with deterministic OCR-style character noise.
- "Embedding" ranking is a lightweight lexical hashing-vector stand-in (real neural embeddings deferred);
  content is served as text bytes, not rendered PDFs.
