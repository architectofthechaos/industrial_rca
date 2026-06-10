"""S2.8 — realism injection harness tests.

Contract: deterministic when seeded; each knob independently and verifiably
changes the output distribution; disabled (rates 0 / skew 0) is a clean no-op.
"""
from datetime import datetime, timezone, timedelta

import pytest

from rca_simulator.realism.config import RealismConfig
from rca_simulator.realism.inject import RealismInjector


# ---------- config ----------

def test_config_defaults_are_clean():
    cfg = RealismConfig()
    assert cfg.clock_skew_seconds == 0.0
    assert cfg.drop_rate == 0.0
    assert cfg.bad_quality_rate == 0.0
    assert cfg.error_5xx_rate == 0.0
    assert cfg.latency_mean_ms == 0.0
    assert cfg.latency_p99_ms == 0.0


def test_config_from_env_parses_all_knobs():
    env = {
        "SIM_CLOCK_SKEW_SECONDS": "2.4",
        "SIM_DROP_RATE": "0.01",
        "SIM_BAD_QUALITY_RATE": "0.005",
        "SIM_5XX_RATE": "0.02",
        "SIM_LATENCY_MEAN_MS": "120",
        "SIM_LATENCY_P99_MS": "2500",
    }
    cfg = RealismConfig.from_env(env)
    assert cfg.clock_skew_seconds == 2.4
    assert cfg.drop_rate == 0.01
    assert cfg.bad_quality_rate == 0.005
    assert cfg.error_5xx_rate == 0.02
    assert cfg.latency_mean_ms == 120.0
    assert cfg.latency_p99_ms == 2500.0


def test_config_from_empty_env_is_clean():
    assert RealismConfig.from_env({}) == RealismConfig()


def test_config_rejects_rate_out_of_range():
    with pytest.raises(ValueError):
        RealismConfig(drop_rate=1.5)


# ---------- determinism ----------

def test_same_seed_same_sequence():
    cfg = RealismConfig(drop_rate=0.3, error_5xx_rate=0.3, bad_quality_rate=0.3)
    a = RealismInjector(cfg, seed=42)
    b = RealismInjector(cfg, seed=42)
    seq_a = [(a.maybe_drop(), a.maybe_error(), a.maybe_bad_quality()) for _ in range(200)]
    seq_b = [(b.maybe_drop(), b.maybe_error(), b.maybe_bad_quality()) for _ in range(200)]
    assert seq_a == seq_b


def test_different_seed_different_sequence():
    cfg = RealismConfig(drop_rate=0.3)
    inj1 = RealismInjector(cfg, seed=1)
    inj2 = RealismInjector(cfg, seed=2)
    seq1 = [inj1.maybe_drop() for _ in range(200)]
    seq2 = [inj2.maybe_drop() for _ in range(200)]
    assert seq1 != seq2


# ---------- drop / error / quality rates ----------

def test_drop_rate_zero_never_drops():
    inj = RealismInjector(RealismConfig(drop_rate=0.0), seed=7)
    assert not any(inj.maybe_drop() for _ in range(500))


def test_drop_rate_matches_configured_frequency():
    inj = RealismInjector(RealismConfig(drop_rate=0.5), seed=7)
    n = 4000
    drops = sum(inj.maybe_drop() for _ in range(n))
    assert 0.45 < drops / n < 0.55


def test_error_rate_matches_configured_frequency():
    inj = RealismInjector(RealismConfig(error_5xx_rate=0.2), seed=7)
    n = 4000
    errs = sum(inj.maybe_error() for _ in range(n))
    assert 0.16 < errs / n < 0.24


def test_bad_quality_rate_matches_configured_frequency():
    inj = RealismInjector(RealismConfig(bad_quality_rate=0.1), seed=7)
    n = 4000
    bad = sum(inj.maybe_bad_quality() for _ in range(n))
    assert 0.07 < bad / n < 0.13


# ---------- clock skew ----------

def test_skew_zero_is_noop():
    inj = RealismInjector(RealismConfig(clock_skew_seconds=0.0), seed=1)
    ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert inj.skew_timestamp(ts) == ts


def test_skew_shifts_timestamp():
    inj = RealismInjector(RealismConfig(clock_skew_seconds=2.5), seed=1)
    ts = datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert inj.skew_timestamp(ts) == ts + timedelta(seconds=2.5)


# ---------- latency ----------

def test_latency_disabled_returns_zero():
    inj = RealismInjector(RealismConfig(latency_mean_ms=0.0, latency_p99_ms=0.0), seed=1)
    assert all(inj.next_latency_ms() == 0.0 for _ in range(100))


def test_latency_typical_near_mean_and_tail_reaches_p99():
    inj = RealismInjector(RealismConfig(latency_mean_ms=100.0, latency_p99_ms=2000.0), seed=3)
    samples = sorted(inj.next_latency_ms() for _ in range(5000))
    median = samples[len(samples) // 2]
    assert 50.0 <= median <= 150.0          # typical near mean
    assert max(samples) >= 1000.0           # tail spikes toward p99


def test_latency_knob_moves_distribution():
    lo = RealismInjector(RealismConfig(latency_mean_ms=10.0, latency_p99_ms=20.0), seed=3)
    hi = RealismInjector(RealismConfig(latency_mean_ms=500.0, latency_p99_ms=5000.0), seed=3)
    lo_avg = sum(lo.next_latency_ms() for _ in range(2000)) / 2000
    hi_avg = sum(hi.next_latency_ms() for _ in range(2000)) / 2000
    assert hi_avg > lo_avg * 10


def test_latency_deterministic_when_seeded():
    cfg = RealismConfig(latency_mean_ms=100.0, latency_p99_ms=2000.0)
    a = RealismInjector(cfg, seed=9)
    b = RealismInjector(cfg, seed=9)
    assert [a.next_latency_ms() for _ in range(300)] == [b.next_latency_ms() for _ in range(300)]
