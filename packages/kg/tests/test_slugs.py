"""Slug utility — single source of truth for canonical-id segments (Sprint 2a §1.3)."""
from rca_kg.slugs import slug


def test_slug_examples():
    assert slug("P-101A") == "p-101a"
    assert slug("UNIT-101") == "unit-101"
    assert slug("Refinery GC") == "refinery-gc"
    assert slug("--Weird__Tag--") == "weird-tag"


def test_mar_seed_uses_shared_slug():
    from rca_mar import seed
    assert seed._slug is slug
