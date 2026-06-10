"""Tests for the echo-path subset of rca_contracts.

Covers: tz-aware enforcement, strict/frozen/extra-forbid config, the 11 ToolError
codes, and the ToolResponse[T] success-XOR-error envelope rule.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rca_contracts import (
    HistorianMode,
    Measurement,
    MeasurementSeries,
    PressureReference,
    Provenance,
    SignalDescriptor,
    TimeBasis,
    ToolError,
    ToolResponse,
    WorkOrder,
)

UTC = timezone.utc


def _signal() -> SignalDescriptor:
    return SignalDescriptor(
        signal_id=uuid4(), tenant_id=uuid4(), asset_id=uuid4(),
        role="discharge_pressure", qudt_unit="http://qudt.org/vocab/unit/PA",
    )


def _time_basis() -> TimeBasis:
    return TimeBasis(
        source_clock="echo", observed_offset_seconds=0.0,
        offset_measurement_time=datetime(2026, 3, 1, tzinfo=UTC),
        source_timezone="UTC", confidence="configured",
    )


def _provenance() -> Provenance:
    return Provenance(
        tool_name="echo.get_series", tool_version="0.1.0", source="echo",
        source_query="GET /echo", queried_at=datetime(2026, 3, 1, tzinfo=UTC),
        response_id=uuid4(), record_count=1, truncated=False,
    )


# ---------- identity / descriptors ----------

def test_signal_descriptor_defaults_pressure_reference():
    assert _signal().pressure_reference is PressureReference.not_applicable


def test_models_are_frozen():
    sig = _signal()
    with pytest.raises(ValidationError):
        sig.role = "other"


def test_models_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        TimeBasis(
            source_clock="echo", observed_offset_seconds=0.0,
            offset_measurement_time=datetime(2026, 3, 1, tzinfo=UTC),
            source_timezone="UTC", confidence="configured", bogus="x",
        )


# ---------- time awareness ----------

def test_measurement_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        Measurement(signal_id=uuid4(), timestamp=datetime(2026, 3, 1), value=1.0)


def test_measurement_accepts_aware_datetime_and_defaults():
    m = Measurement(signal_id=uuid4(), timestamp=datetime(2026, 3, 1, tzinfo=UTC), value=1.5)
    assert m.quality == "good"
    assert m.is_interpolated is False


# ---------- measurement series ----------

def test_measurement_series_holds_mode_and_values():
    sig = _signal()
    ms = MeasurementSeries(
        signal=sig, time_basis=_time_basis(), mode=HistorianMode.interpolated,
        interpolation_method="linear",
        values=[Measurement(signal_id=sig.signal_id,
                            timestamp=datetime(2026, 3, 1, tzinfo=UTC), value=1.0)],
    )
    assert ms.mode is HistorianMode.interpolated
    assert len(ms.values) == 1


def test_measurement_series_python_round_trips():
    sig = _signal()
    ms = MeasurementSeries(signal=sig, time_basis=_time_basis(), mode=HistorianMode.stored,
                           aggregation_interval=timedelta(minutes=15), values=[])
    assert MeasurementSeries.model_validate(ms.model_dump()) == ms


# ---------- tool error ----------

def test_work_order_parses_and_restricts_source_system():
    wo = WorkOrder(
        work_order_id="10000123", asset_id=uuid4(),
        opened_at=datetime(2026, 3, 18, tzinfo=UTC), closed_at=None,
        priority="1", status="M2", failure_code="LEK",
        description="seal leak", source_system="sap_pm",
    )
    assert wo.source_system == "sap_pm"
    with pytest.raises(ValidationError):
        WorkOrder(
            work_order_id="x", asset_id=uuid4(), opened_at=datetime(2026, 3, 1, tzinfo=UTC),
            closed_at=None, priority="1", status="open", description="d",
            source_system="oracle",            # not a known source
        )


def test_tool_error_valid_code():
    err = ToolError(code="source_unavailable", message="down", retryable=True)
    assert err.retryable is True


def test_tool_error_rejects_unknown_code():
    with pytest.raises(ValidationError):
        ToolError(code="nope", message="x", retryable=False)


# ---------- tool response envelope ----------

def test_tool_response_ok_carries_data_and_provenance():
    sig = _signal()
    ms = MeasurementSeries(signal=sig, time_basis=_time_basis(), mode=HistorianMode.stored, values=[])
    resp = ToolResponse[MeasurementSeries].ok(ms, _provenance())
    assert resp.data == ms and resp.provenance is not None and resp.error is None


def test_tool_response_fail_carries_error_only():
    resp = ToolResponse[MeasurementSeries].fail(
        ToolError(code="timeout", message="slow", retryable=True)
    )
    assert resp.error is not None and resp.data is None and resp.provenance is None


def test_tool_response_rejects_data_without_provenance():
    sig = _signal()
    ms = MeasurementSeries(signal=sig, time_basis=_time_basis(), mode=HistorianMode.stored, values=[])
    with pytest.raises(ValidationError):
        ToolResponse[MeasurementSeries](data=ms)            # provenance missing


def test_tool_response_rejects_data_and_error_together():
    sig = _signal()
    ms = MeasurementSeries(signal=sig, time_basis=_time_basis(), mode=HistorianMode.stored, values=[])
    with pytest.raises(ValidationError):
        ToolResponse[MeasurementSeries](
            data=ms, provenance=_provenance(),
            error=ToolError(code="internal_error", message="x", retryable=False),
        )


def test_tool_response_rejects_empty():
    with pytest.raises(ValidationError):
        ToolResponse[MeasurementSeries]()


def test_tool_response_round_trips_json():
    sig = _signal()
    ms = MeasurementSeries(signal=sig, time_basis=_time_basis(), mode=HistorianMode.stored, values=[])
    resp = ToolResponse[MeasurementSeries].ok(ms, _provenance())
    again = ToolResponse[MeasurementSeries].model_validate_json(resp.model_dump_json())
    assert again == resp
