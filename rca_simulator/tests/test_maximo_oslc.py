"""S2.3 — Maximo OSLC query parsing + scenario seeding (pure, no HTTP)."""
from pathlib import Path

from rca_simulator.fixtures.loader import load
from rca_simulator.maximo.oslc import apply_select, apply_where, paginate, parse_where
from rca_simulator.maximo.seed import (
    seed_failure_reports,
    seed_work_orders,
    to_local_naive,
)

REFPLANT = Path(__file__).resolve().parents[1] / "fixtures" / "refplant"
ISO_14224_CODES = {"LEK", "VIB", "ELP", "STP", "ELE", "ERO", "INL"}


def rp():
    return load(REFPLANT)


# ---------- oslc.where ----------

def test_parse_single_equality():
    conds = parse_where('location="CRDU-P101A"')
    assert conds == [("location", "=", "CRDU-P101A")]


def test_parse_and_with_comparison():
    conds = parse_where('status="COMP" and reportdate>="2026-03-01"')
    assert ("status", "=", "COMP") in conds
    assert ("reportdate", ">=", "2026-03-01") in conds


def test_apply_where_filters_records():
    recs = [{"location": "A", "status": "COMP"}, {"location": "B", "status": "WAPPR"}]
    out = apply_where(recs, parse_where('location="A"'))
    assert out == [{"location": "A", "status": "COMP"}]


def test_apply_where_comparison_operator():
    recs = [{"reportdate": "2026-01-01"}, {"reportdate": "2026-06-01"}]
    out = apply_where(recs, parse_where('reportdate>="2026-03-01"'))
    assert out == [{"reportdate": "2026-06-01"}]


# ---------- oslc.select / paging ----------

def test_apply_select_projects_fields():
    recs = [{"wonum": "1", "status": "COMP", "location": "A"}]
    assert apply_select(recs, "wonum,status") == [{"wonum": "1", "status": "COMP"}]


def test_paginate_slices_and_reports_total():
    recs = [{"n": i} for i in range(10)]
    page, total = paginate(recs, page_size=3, page=2)
    assert total == 10
    assert page == [{"n": 3}, {"n": 4}, {"n": 5}]


# ---------- seeding ----------

def test_seed_includes_scenario_and_baseline_work_orders():
    wos = seed_work_orders(rp())
    wonums = {w["wonum"] for w in wos}
    assert {"WO-50012345", "WO-50012402"} <= wonums   # seal-leak scenario WOs
    assert "WO-49900001" in wonums                    # 2025 Q4 baseline seed


def test_seal_leak_work_orders_map_to_p101a_location():
    wos = seed_work_orders(rp())
    p101a = [w for w in wos if w["wonum"] in {"WO-50012345", "WO-50012402"}]
    assert all(w["location"] == "CRDU-P101A" for w in p101a)


def test_reportdate_is_local_without_timezone():
    wos = seed_work_orders(rp())
    sample = next(w for w in wos if w["wonum"] == "WO-50012402")["reportdate"]
    assert "Z" not in sample and "+" not in sample    # naive local time


def test_at_least_one_failure_report_uses_a_legacy_code():
    codes = {f["failurecode"] for f in seed_failure_reports(rp())}
    assert codes & ISO_14224_CODES                    # some ISO codes present
    assert codes - ISO_14224_CODES                    # ...and at least one legacy code


def test_to_local_naive_strips_tzinfo():
    from datetime import datetime, timezone
    utc = datetime(2026, 3, 1, 6, 0, tzinfo=timezone.utc)
    naive = to_local_naive(utc, "America/Chicago")
    assert naive.endswith("00:00:00") or ":" in naive
    assert "+" not in naive and "Z" not in naive
