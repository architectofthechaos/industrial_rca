from datetime import datetime, timezone
from rca_agents.mcp_toolbox import (
    summarize_series, alarm_to_log, descriptor_to_summary, severity_for,
)

REF = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)


def test_summarize_series_computes_stats_and_trend():
    import pytest
    series = {"tag": {"tag_name": "P-101A.vibration_radial"},
              "values": [{"value": 2.1}, {"value": 4.0}, {"value": 6.6}]}
    out = summarize_series(series, role="vibration_radial", lookback_hours=720)
    assert out["tag_name"] == "P-101A.vibration_radial"
    assert out["role"] == "vibration_radial"
    assert out["mean"] == pytest.approx(4.2333, abs=1e-3)
    assert out["max"] == 6.6
    assert out["severity"] in {"normal", "elevated", "critical"}
    assert "6.6" in out["summary"]


def test_severity_rule():
    assert severity_for(mean=2.0, mx=6.6) == "critical"
    assert severity_for(mean=4.0, mx=6.0) == "elevated"
    assert severity_for(mean=10.0, mx=11.0) == "normal"


def test_alarm_to_log_renames():
    a = {"message": "slight whine", "timestamp": "2026-03-06T00:00:00+00:00", "tag_name": "P-101A"}
    log = alarm_to_log(a, index=0, canonical_id="asset:r:u:p-101a")
    assert log["text"] == "slight whine"
    assert log["at"] == "2026-03-06T00:00:00+00:00"
    assert log["author"] is None
    assert log["log_id"]


def test_descriptor_to_summary_synthesizes_name_and_confidence():
    d = {"canonical_id": "asset:r:u:p-101a", "tag": "P-101A", "service": "charge pump"}
    s = descriptor_to_summary(d, keywords="P-101A seal leak")
    assert s["canonical_id"] == "asset:r:u:p-101a"
    assert s["name"] == "P-101A"
    assert 0.0 < s["confidence"] <= 1.0
