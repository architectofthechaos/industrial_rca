"""S13.5 OPC UA connector — hermetic unit test of the value mapping (no server)."""
import pytest
from rca_connector_sdk import SourceBinding
from rca_contracts import PressureReference, TagDescriptor

from rca_connector_opc_ua.connector import to_measurement


def test_to_measurement_converts_psig_to_pa_gauge():
    tag = TagDescriptor(
        canonical_id="asset:refinery-gc:unit-101:p-101a",
        tag_name="P-101A.discharge_pressure",
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.gauge,
    )
    m = to_measurement(tag, SourceBinding(handle="P-101A.discharge_pressure", raw_unit="psig"), 14.5)
    assert m.value == pytest.approx(14.5 * 6_894.757293168)   # psig -> Pa (gauge)
    assert m.quality == "good" and m.timestamp.tzinfo is not None
