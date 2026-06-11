"""ok_response: full provenance population + ToolResponse.ok wrapping (any payload type)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel

from rca_connector_sdk import ok_response
from rca_contracts import ToolResponse


class _Payload(BaseModel):
    x: int


def test_ok_response_populates_every_provenance_field():
    before = datetime.now(timezone.utc)
    resp = ok_response(["a", "b"], tool="t.list", version="1.2.3", source="unit-test",
                       source_query="q?x=1", record_count=2, raw_tags=["a", "b"],
                       notes="partial")
    after = datetime.now(timezone.utc)
    assert resp.error is None
    assert resp.data == ["a", "b"]
    p = resp.provenance
    assert p is not None
    assert p.tool_name == "t.list"
    assert p.tool_version == "1.2.3"
    assert p.source == "unit-test"
    assert p.source_query == "q?x=1"
    assert p.record_count == 2
    assert p.raw_tags == ["a", "b"]
    assert p.notes == "partial"
    assert p.truncated is False
    assert isinstance(p.response_id, UUID)
    assert before <= p.queried_at <= after


def test_ok_response_defaults_raw_tags_empty_and_notes_none():
    resp = ok_response(_Payload(x=1), tool="t.get", version="0.1.0", source="s",
                       source_query="get 1", record_count=1)
    assert resp.data == _Payload(x=1)
    assert resp.provenance is not None
    assert resp.provenance.raw_tags == []
    assert resp.provenance.notes is None


def test_ok_response_mints_a_fresh_response_id_per_call():
    common = dict(tool="t", version="0", source="s", source_query="q", record_count=0)
    a = ok_response([], **common)
    b = ok_response([], **common)
    assert a.provenance is not None and b.provenance is not None
    assert a.provenance.response_id != b.provenance.response_id


def test_ok_response_revalidates_under_a_parametrized_envelope():
    """Servers annotate -> ToolResponse[T]; the agnostic envelope must round-trip into it."""
    resp = ok_response(_Payload(x=7), tool="t.get", version="0.1.0", source="s",
                       source_query="get 7", record_count=1)
    wired = ToolResponse[_Payload].model_validate_json(resp.model_dump_json())
    assert wired.data == _Payload(x=7)
    assert wired.provenance == resp.provenance
