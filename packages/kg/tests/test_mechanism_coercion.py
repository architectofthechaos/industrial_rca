"""persist_failure_event coerces an unknown mechanism to the seeded "Other" node (Sprint 5 G26).

The rank-hypotheses prompt is given valid failure-MODE codes but not the mechanism vocabulary, so
the live LLM emitted an out-of-ontology iso14224_mechanism ('PLU', actually a failure *mode* code)
and the close phase hard-failed. We coerce an unknown mechanism to ``failure-mechanism:other``
(a real seeded node) rather than failing the probe — the failure *mode* still hard-fails (modes
ARE given to the LLM). Reuses the in-memory graph fixture from test_asset_layer.
"""
from __future__ import annotations

import pytest

from rca_kg.assets import InvalidFailureModePair
from test_asset_layer import _graph, P101A, REF_TIME


@pytest.mark.asyncio
async def test_persist_coerces_unknown_mechanism_to_other():
    g = _graph()
    created = await g.persist_failure_event(
        event_id="fe-coerce", probe_run_id="pr", conclusion_id="c", canonical_id=P101A,
        iso14224_failure_mode="ELP", iso14224_mechanism="PLU",   # 'PLU' is not a mechanism
        iso14224_cause=None, narrative="seal leak", confidence=0.6,
        detected_at=REF_TIME, concluded_at=REF_TIME, engineer_approval_status="approved")
    assert created is True   # coerced, not rejected
    event = g.nodes[("HistoricalFailureEvent", "fe-coerce")]
    assert event["iso14224_mechanism"] == "failure-mechanism:other"


@pytest.mark.asyncio
async def test_persist_still_rejects_unknown_failure_mode():
    g = _graph()
    with pytest.raises(InvalidFailureModePair):
        await g.persist_failure_event(
            event_id="fe-badmode", probe_run_id="pr", conclusion_id="c", canonical_id=P101A,
            iso14224_failure_mode="NOPE", iso14224_mechanism="failure-mechanism:leakage",
            iso14224_cause=None, narrative="x", confidence=0.5,
            detected_at=REF_TIME, concluded_at=REF_TIME, engineer_approval_status="approved")
