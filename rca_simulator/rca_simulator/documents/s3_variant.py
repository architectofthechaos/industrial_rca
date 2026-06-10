"""S2.6 — optional S3-compatible (MinIO) variant of the document store.

Seeds a MinIO bucket with the fixture documents and exposes GetObject /
ListObjectsV2-style helpers, so a documents connector configured for S3 can read
the same corpus. Requires a live MinIO endpoint, so this path is exercised by the
docker-compose stack / EPIC-013 integration tests rather than the unit suite.
"""
from __future__ import annotations

import io
from pathlib import Path

from .search_index import Document, load_documents, ocr_noise, seed_from_id


def _object_bytes(doc: Document) -> bytes:
    text = ocr_noise(doc.text, seed=seed_from_id(doc.doc_id)) if doc.scanned else doc.text
    return text.encode("utf-8")


def _object_key(doc: Document) -> str:
    return f"{doc.doc_type}/{doc.doc_id}.pdf"


def seed_bucket(client, bucket: str, docs_dir: str | Path) -> list[str]:
    """Create ``bucket`` (if missing) and upload every fixture document.

    ``client`` is a ``minio.Minio`` instance. Returns the object keys written.
    """
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    keys: list[str] = []
    for doc in load_documents(docs_dir):
        data = _object_bytes(doc)
        key = _object_key(doc)
        client.put_object(bucket, key, io.BytesIO(data), length=len(data),
                          content_type="application/pdf")
        keys.append(key)
    return keys


def main() -> None:
    """Seed MinIO from env config (used by docker-compose)."""
    import os

    from minio import Minio

    endpoint = os.environ.get("S3_ENDPOINT", "localhost:9000")
    client = Minio(
        endpoint,
        access_key=os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("S3_SECRET_KEY", "minioadmin"),
        secure=os.environ.get("S3_SECURE", "false").lower() == "true",
    )
    bucket = os.environ.get("S3_BUCKET", "refplant-docs")
    docs = os.environ.get("DOCS_PATH", "fixtures/refplant/documents")
    keys = seed_bucket(client, bucket, docs)
    print(f"seeded {len(keys)} objects into {bucket}")


if __name__ == "__main__":
    main()


__all__ = ["seed_bucket", "main"]
