"""SDK pure-helper tests: units, time, errors, retry, provenance accumulator."""
from datetime import datetime, timezone

import httpx
import pytest

from rca_connector_sdk.errors import (
    ConnectorError,
    SourceUnavailable,
    UnitConversionAmbiguous,
    map_source_error,
)
from rca_connector_sdk.provenance import ProvenanceAccumulator, ProvenanceMissingError
from rca_connector_sdk.retry import with_retry
from rca_connector_sdk.timeutil import to_utc
from rca_connector_sdk.units import to_si

UTC = timezone.utc


# ---------- units ----------

def test_to_si_converts_known_units():
    assert to_si(1.0, "bar", "http://qudt.org/vocab/unit/PA") == pytest.approx(100_000.0)
    assert to_si(20.0, "degC", "http://qudt.org/vocab/unit/K") == pytest.approx(293.15)
    assert to_si(5.0, "Pa", "http://qudt.org/vocab/unit/PA") == 5.0


def test_to_si_converts_gauge_pressure_when_reference_is_gauge():
    from rca_contracts import PressureReference
    # psig -> Pa magnitude, staying gauge (no absolute conversion needed)
    assert to_si(10.0, "psig", "http://qudt.org/vocab/unit/PA",
                 PressureReference.gauge) == pytest.approx(10 * 6_894.757293168)


def test_to_si_refuses_gauge_to_absolute_without_atmos_ref():
    from rca_contracts import PressureReference
    with pytest.raises(UnitConversionAmbiguous):
        to_si(10.0, "psig", "http://qudt.org/vocab/unit/PA", PressureReference.absolute)


def test_to_si_refuses_unknown_unit():
    with pytest.raises(UnitConversionAmbiguous):
        to_si(1.0, "smoots", "http://qudt.org/vocab/unit/PA")


# ---------- time ----------

def test_to_utc_localizes_naive_via_source_tz():
    naive = datetime(2026, 3, 1, 6, 0, 0)
    assert to_utc(naive, "America/Chicago") == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)  # CST -6


def test_to_utc_converts_aware_to_utc():
    aware = datetime(2026, 3, 1, 6, 0, tzinfo=timezone(offset=-__import__("datetime").timedelta(hours=5)))
    assert to_utc(aware, "UTC") == datetime(2026, 3, 1, 11, 0, tzinfo=UTC)


# ---------- errors ----------

def test_map_connector_errors_preserve_code_and_retryable():
    assert map_source_error(SourceUnavailable("down")).code == "source_unavailable"
    assert map_source_error(SourceUnavailable("down")).retryable is True
    amb = map_source_error(UnitConversionAmbiguous("psig"))
    assert amb.code == "unit_conversion_ambiguous" and amb.retryable is False


def test_map_httpx_errors():
    assert map_source_error(httpx.ConnectError("boom")).code == "source_unavailable"
    assert map_source_error(httpx.TimeoutException("slow")).code == "timeout"


def test_map_unknown_error_is_internal():
    err = map_source_error(ValueError("oops"))
    assert err.code == "internal_error" and err.retryable is False


# ---------- retry ----------

async def test_with_retry_recovers_then_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise SourceUnavailable("transient")
        return "ok"

    assert await with_retry(flaky, attempts=3) == "ok"
    assert calls["n"] == 3


async def test_with_retry_reraises_after_exhaustion():
    async def always_fail():
        raise SourceUnavailable("down")

    with pytest.raises(ConnectorError):
        await with_retry(always_fail, attempts=2)


# ---------- provenance accumulator ----------

def test_provenance_build_fails_if_never_recorded():
    acc = ProvenanceAccumulator()
    with pytest.raises(ProvenanceMissingError):
        acc.build(tool_name="t", tool_version="0.1.0", source="echo",
                  queried_at=datetime(2026, 3, 1, tzinfo=UTC), response_id=__import__("uuid").uuid4())


def test_provenance_build_succeeds_after_record():
    acc = ProvenanceAccumulator()
    acc.record(source_query="GET /echo", raw_tags=["RAW.TAG"], record_count=3)
    prov = acc.build(tool_name="echo.series", tool_version="0.1.0", source="echo",
                     queried_at=datetime(2026, 3, 1, tzinfo=UTC),
                     response_id=__import__("uuid").uuid4())
    assert prov.record_count == 3 and prov.raw_tags == ["RAW.TAG"] and prov.source_query == "GET /echo"
