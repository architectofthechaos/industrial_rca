"""parse_canonical_id + the entity-vocabulary contract surface (Sprint 2b)."""
import pytest

from rca_contracts import CanonicalParts, parse_canonical_id


def test_parse_canonical_id_happy():
    parts = parse_canonical_id("asset:refinery-gc:unit-101:p-101a")
    assert isinstance(parts, CanonicalParts)
    assert parts.plant_id == "refinery-gc"
    assert parts.unit_slug == "unit-101"
    assert parts.name_slug == "p-101a"


@pytest.mark.parametrize(
    "bad",
    [
        "refinery-gc:unit-101:p-101a",          # missing 'asset:' prefix
        "asset:refinery-gc:unit-101",           # too few segments
        "asset:refinery-gc:unit-101:p-101a:x",  # too many segments
        "asset:Refinery:unit-101:p-101a",       # uppercase not allowed
        "asset:refinery_gc:unit-101:p-101a",    # underscore not allowed
        "asset::unit-101:p-101a",               # empty segment
        "",                                     # empty string
    ],
)
def test_parse_canonical_id_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_canonical_id(bad)
