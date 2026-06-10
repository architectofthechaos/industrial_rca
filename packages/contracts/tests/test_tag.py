"""ResolveTagOutput contract."""
from uuid import uuid4

import pytest
from pydantic import ValidationError
from rca_contracts import PressureReference, ResolveTagOutput, SignalDescriptor


def _sig(**over) -> SignalDescriptor:
    base = dict(signal_id=uuid4(), tenant_id=uuid4(), asset_id=uuid4(),
                role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
                pressure_reference=PressureReference.gauge)
    base.update(over)
    return SignalDescriptor(**base)


def test_resolve_tag_output_roundtrips():
    out = ResolveTagOutput(status="resolved", signal=_sig(), confidence=1.0,
                           mapping_source="authoritative_import", alternatives=[])
    again = ResolveTagOutput.model_validate_json(out.model_dump_json())
    assert again.status == "resolved" and again.signal == out.signal


def test_resolve_tag_output_unresolved_has_no_signal():
    out = ResolveTagOutput(status="unresolved", signal=None, confidence=0.0,
                           mapping_source="none", alternatives=[])
    assert out.signal is None


def test_resolve_tag_output_frozen():
    with pytest.raises(ValidationError):
        ResolveTagOutput(status="resolved", signal=_sig(), confidence=1.0,
                         mapping_source="x", alternatives=[]).status = "unresolved"
