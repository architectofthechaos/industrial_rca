"""Provenance.connection_id (Sprint 2b audit trail) + the SignalID removal guard."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from rca_contracts import Provenance

UTC = timezone.utc


def _prov(**over) -> Provenance:
    base = dict(
        tool_name="pi.get_series", tool_version="0.1.0", source="pi",
        source_query="GET /streams", queried_at=datetime(2026, 3, 1, tzinfo=UTC),
        response_id=uuid4(), record_count=1, truncated=False,
    )
    base.update(over)
    return Provenance(**base)


def test_provenance_connection_id_defaults_none():
    assert _prov().connection_id is None


def test_provenance_accepts_connection_id():
    assert _prov(connection_id="conn-pi-main").connection_id == "conn-pi-main"


def test_signal_id_import_removed():
    with pytest.raises(ImportError):
        from rca_contracts import SignalID  # noqa: F401


def test_signal_descriptor_import_removed():
    with pytest.raises(ImportError):
        from rca_contracts import SignalDescriptor  # noqa: F401
