"""S2.6 — SharePoint / S3 document simulator (HTTP REST).

Stands in for SharePoint (Search + Graph drive-item) with an optional
S3-compatible MinIO variant. Serves fixture documents: datasheets, simplified
P&IDs, prior RCA reports, operator narratives — scenario-matched, some with
injected OCR noise.

Modules
-------
app.py           FastAPI Search + Graph drive-item routes.
search_index.py  Local BM25 + embedding index over fixture documents.
s3_variant.py    MinIO seeding + GetObject / ListObjectsV2.
Dockerfile       Container image.

Ref: SPEC-007 (SharePoint/S3 section), TASK-S2.6.
"""
