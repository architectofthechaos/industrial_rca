"""Neo4j temporal coercion (Sprint 5 G23).

Neo4j returns datetime node properties as ``neo4j.time.DateTime``, which Pydantic rejects for a
``datetime`` field. The live flywheel run surfaced this: reading a *materialized* asset back via
``get_asset_context`` failed to build ``AssetContextSummary`` (materialized_at/last_probed_at).
Hermetic KG tests use ``InMemoryAssetGraph`` (python datetimes), so this was invisible.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rca_kg.assets import AssetContextSummary, _native_props


def test_native_props_converts_neo4j_datetime():
    import neo4j.time

    ndt = neo4j.time.DateTime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
    out = _native_props({"materialized_at": ndt, "name": "P-101A", "n": 3})
    assert isinstance(out["materialized_at"], datetime)
    assert out["materialized_at"].year == 2026 and out["materialized_at"].hour == 12
    assert out["name"] == "P-101A" and out["n"] == 3      # non-temporal values untouched


def test_asset_context_summary_validates_after_coercion():
    import neo4j.time

    props = {
        "id": "asset:refinery-gc:unit-101:p-101a", "name": "P-101A",
        "plant_id": "refinery-gc", "unit_slug": "unit-101",
        "iso14224_class": "equipment-class:bb1",
        "materialized_at": neo4j.time.DateTime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc),
        "last_probed_at": neo4j.time.DateTime(2026, 3, 30, 12, 5, 0, tzinfo=timezone.utc),
    }
    summary = AssetContextSummary.model_validate(_native_props(props))
    assert summary.id == "asset:refinery-gc:unit-101:p-101a"
    assert isinstance(summary.materialized_at, datetime)
