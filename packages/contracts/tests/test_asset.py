"""AssetDescriptor + resolve I/O contracts."""
from uuid import uuid4

import pytest
from pydantic import ValidationError
from rca_contracts import (
    AssetDescriptor,
    ResolveAssetOutput,
)


def _asset(**over) -> AssetDescriptor:
    base = dict(
        asset_id=uuid4(), canonical_id="asset:refinery-gc:unit-101:p-101a",
        tenant_id=uuid4(), plant_id="refinery-gc",
        iso14224_class="pump.centrifugal", iso14224_level=6, tag="P-101A",
        service="charge pump", criticality="A", manufacturer="Sulzer",
        model="AHLSTAR-A22-50", serial_number="SN-1", commissioned_at=None,
        decommissioned_at=None, location_description=None, description=None,
    )
    base.update(over)
    return AssetDescriptor(**base)


def test_asset_descriptor_roundtrips():
    a = _asset()
    again = AssetDescriptor.model_validate_json(a.model_dump_json())
    assert again == a


def test_asset_descriptor_carries_dual_keys():
    a = _asset()
    assert a.canonical_id == "asset:refinery-gc:unit-101:p-101a"
    assert a.plant_id == "refinery-gc"


def test_asset_descriptor_requires_canonical_id():
    base = _asset().model_dump()
    del base["canonical_id"]
    with pytest.raises(ValidationError):
        AssetDescriptor(**base)


def test_asset_descriptor_rejects_bad_criticality():
    with pytest.raises(ValidationError):
        _asset(criticality="high")           # only A/B/C/D allowed


def test_asset_descriptor_is_frozen():
    with pytest.raises(ValidationError):
        _asset().tag = "X"


def test_asset_descriptor_has_no_parent_pointer():
    # Hierarchy moved to the KG (Sprint 2); extra="forbid" must reject the old parent field.
    with pytest.raises(ValidationError):
        _asset(parent_asset_id=uuid4())


def test_resolve_output_roundtrips():
    a = _asset()
    out = ResolveAssetOutput(
        status="resolved", asset=a, canonical_id=a.canonical_id, confidence=1.0,
        mapping_source="exact_match", alternatives=[],
    )
    again = ResolveAssetOutput.model_validate_json(out.model_dump_json())
    assert again.status == "resolved" and again.asset == out.asset
    assert again.canonical_id == "asset:refinery-gc:unit-101:p-101a"


def test_resolve_output_unresolved_has_no_asset():
    out = ResolveAssetOutput(status="unresolved", asset=None, canonical_id=None,
                             confidence=0.0, mapping_source="none", alternatives=[])
    assert out.asset is None and out.canonical_id is None
