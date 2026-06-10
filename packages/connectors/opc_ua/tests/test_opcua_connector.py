"""S13.5 OPC UA connector — hermetic unit test of the value mapping (no server)."""
from uuid import uuid4

import pytest
from rca_connector_sdk import SourceBinding
from rca_contracts import PressureReference, SignalDescriptor

from rca_connector_opc_ua.connector import to_measurement


def test_to_measurement_converts_psig_to_pa_gauge():
    sig = SignalDescriptor(
        signal_id=uuid4(), tenant_id=uuid4(), asset_id=uuid4(),
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
        pressure_reference=PressureReference.gauge,
    )
    m = to_measurement(sig, SourceBinding(handle="P-101A.discharge_pressure", raw_unit="psig"), 14.5)
    assert m.value == pytest.approx(14.5 * 6_894.757293168)   # psig -> Pa (gauge)
    assert m.signal_id == sig.signal_id
    assert m.quality == "good" and m.timestamp.tzinfo is not None
