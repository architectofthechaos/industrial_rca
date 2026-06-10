"""S2.6 — document search-index tests (pure, no HTTP).

A scenario-relevant query returns the matching seeded documents ranked sensibly,
deterministically.
"""
from pathlib import Path

from rca_simulator.documents.search_index import DocumentIndex, load_documents

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "refplant" / "documents"


def index():
    return DocumentIndex(load_documents(DOCS))


def test_loads_all_documents():
    docs = load_documents(DOCS)
    ids = {d.doc_id for d in docs}
    assert {"DS-P101A", "RCA-2025-014", "RCA-2024-009"} <= ids
    assert len(docs) == 6


def test_mechanical_seal_query_ranks_seal_docs_first():
    results = index().search("mechanical seal flush leak", top_k=3)
    top_assets = {r.document.asset for r in results[:2]}
    assert "P-101A" in top_assets
    assert results[0].document.doc_id in {"DS-P101A", "RCA-2025-014"}


def test_cavitation_query_finds_bfw_pump():
    results = index().search("cavitation NPSH suction strainer", top_k=3)
    assert results[0].document.asset == "P-101B"


def test_bearing_query_finds_injection_pump_rca():
    results = index().search("bearing wear alignment vibration", top_k=3)
    assert results[0].document.doc_id == "RCA-2024-009"


def test_search_is_deterministic_and_respects_top_k():
    idx = index()
    a = [(r.document.doc_id, round(r.score, 6)) for r in idx.search("seal", top_k=2)]
    b = [(r.document.doc_id, round(r.score, 6)) for r in idx.search("seal", top_k=2)]
    assert a == b
    assert len(idx.search("pump", top_k=2)) == 2


def test_irrelevant_query_scores_low():
    # No term overlap -> BM25 contributes 0; only tiny hash-collision noise remains.
    results = index().search("xyzzy quantum teapot", top_k=5)
    assert all(r.score < 0.1 for r in results)
