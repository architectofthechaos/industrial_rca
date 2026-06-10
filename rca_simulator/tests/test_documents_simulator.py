"""S2.6 — document HTTP simulator tests (FastAPI TestClient, no network).

SharePoint-style search returns ranked hits; Graph drive-item returns metadata
and document bytes (with injected OCR noise on scanned docs).
"""
from pathlib import Path

from fastapi.testclient import TestClient

from rca_simulator.documents.app import create_app
from rca_simulator.documents.search_index import load_documents

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "refplant" / "documents"


def client():
    return TestClient(create_app(DOCS))


def test_search_returns_ranked_hits_for_scenario_query():
    r = client().get("/search", params={"q": "mechanical seal flush leak", "top": 3})
    assert r.status_code == 200
    hits = r.json()["value"]
    assert hits
    assert hits[0]["asset"] == "P-101A"
    assert hits[0]["webUrl"].endswith(hits[0]["id"])


def test_drive_item_metadata():
    r = client().get("/drives/refplant/items/DS-P101A")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "DS-P101A"
    assert "name" in body and body["file"]["mimeType"]


def test_clean_document_content_is_exact_text():
    docs = {d.doc_id: d for d in load_documents(DOCS)}
    r = client().get("/drives/refplant/items/DS-P101A/content")
    assert r.status_code == 200
    assert r.content.decode("utf-8") == docs["DS-P101A"].text   # not scanned: clean


def test_scanned_document_content_has_ocr_noise():
    docs = {d.doc_id: d for d in load_documents(DOCS)}
    scanned_id = "PID-U101"
    assert docs[scanned_id].scanned
    r = client().get(f"/drives/refplant/items/{scanned_id}/content")
    served = r.content.decode("utf-8")
    assert served != docs[scanned_id].text          # OCR noise injected
    assert len(served) == len(docs[scanned_id].text)  # noise is char-level, length-stable


def test_content_is_deterministic_across_requests():
    c = client()
    a = c.get("/drives/refplant/items/PID-U101/content").content
    b = c.get("/drives/refplant/items/PID-U101/content").content
    assert a == b


def test_unknown_item_returns_404():
    c = client()
    assert c.get("/drives/refplant/items/NOPE").status_code == 404
    assert c.get("/drives/refplant/items/NOPE/content").status_code == 404
