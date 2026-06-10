"""S2.6 — document loader + search index over the fixture documents.

Ranking combines BM25 (rank_bm25) with a lightweight lexical hashing-vector
cosine standing in for a neural embedding index (real embeddings are deferred —
MVP keeps search hermetic and dependency-light). Deterministic for a given corpus.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-z0-9]+")
_HASH_DIM = 256


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    doc_type: str
    asset: str
    text: str
    scanned: bool = False

    @property
    def body(self) -> str:
        return f"{self.title} {self.text}"


@dataclass(frozen=True)
class SearchResult:
    document: Document
    score: float


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def load_documents(docs_dir: str | Path) -> list[Document]:
    root = Path(docs_dir)
    docs: list[Document] = []
    for path in sorted(root.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        docs.append(Document(
            doc_id=data["doc_id"], title=data["title"], doc_type=data["doc_type"],
            asset=data["asset"], text=data["text"], scanned=data.get("scanned", False),
        ))
    return docs


def _hash_vector(tokens: list[str]) -> list[float]:
    vec = [0.0] * _HASH_DIM
    for tok in tokens:
        vec[hash_token(tok)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def hash_token(tok: str) -> int:
    # stable across processes (builtin hash is salted)
    import hashlib
    return int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "big") % _HASH_DIM


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class DocumentIndex:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self._corpus_tokens = [_tokenize(d.body) for d in documents]
        self._bm25 = BM25Okapi(self._corpus_tokens) if documents else None
        self._vectors = [_hash_vector(toks) for toks in self._corpus_tokens]

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        if not self.documents or self._bm25 is None:
            return []
        q_tokens = _tokenize(query)
        bm25_scores = self._bm25.get_scores(q_tokens)
        q_vec = _hash_vector(q_tokens)
        cos = [_cosine(q_vec, v) for v in self._vectors]

        bm_max = max(bm25_scores) or 1.0
        results = []
        for doc, bm, c in zip(self.documents, bm25_scores, cos):
            score = 0.7 * (bm / bm_max) + 0.3 * c
            results.append(SearchResult(document=doc, score=round(score, 9)))
        results.sort(key=lambda r: (r.score, r.document.doc_id), reverse=True)
        return results[:top_k]


_OCR_CONFUSIONS = {"o": "0", "l": "1", "i": "1", "s": "5", "e": "c", "n": "m"}


def ocr_noise(text: str, seed: int = 0, rate: float = 0.08) -> str:
    """Deterministically inject length-stable OCR-style character confusions.

    Models a scanned PDF: some letters are misread (o->0, l->1, ...). Seeded so
    the same document always yields the same noisy bytes.
    """
    import random

    rng = random.Random(seed)
    chars = list(text)
    for i, ch in enumerate(chars):
        low = ch.lower()
        if low in _OCR_CONFUSIONS and rng.random() < rate:
            chars[i] = _OCR_CONFUSIONS[low]
    return "".join(chars)


def seed_from_id(doc_id: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.md5(doc_id.encode()).digest()[:4], "big")


__all__ = [
    "Document", "SearchResult", "DocumentIndex", "load_documents",
    "ocr_noise", "seed_from_id",
]
