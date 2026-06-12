"""Env-configurable embedding model + dimension (D15). The vector(N) column width is fixed at
migration time to the default model's dim (1024 for voyage-3); HashEmbeddingTransport must emit the
SAME dim so hermetic tests exercise the real query path."""
from __future__ import annotations

import os

DEFAULT_MODEL = "voyage-3"
DEFAULT_DIM = 1024


def embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)


def embedding_dim() -> int:
    return int(os.environ.get("EMBEDDING_DIM", str(DEFAULT_DIM)))
