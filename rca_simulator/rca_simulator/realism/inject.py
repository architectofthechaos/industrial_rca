"""S2.8 — realism injection hooks shared by every simulator.

A single ``RealismInjector`` instance wraps a simulator's response path. All
randomness flows through one seeded ``random.Random`` so behaviour is
reproducible for a given (seed, config). The hooks are protocol-agnostic — an
HTTP, OPC UA, or MQTT simulator uses the same instance identically.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta

from .config import RealismConfig

# Fraction of latency samples that land in the heavy tail (toward p99).
_TAIL_FRACTION = 0.01


class RealismInjector:
    def __init__(self, config: RealismConfig, seed: int | None = None) -> None:
        self.config = config
        self._rng = random.Random(seed)

    # --- discrete decisions ---

    def maybe_drop(self) -> bool:
        """True when this interval/message should be dropped."""
        return self._rng.random() < self.config.drop_rate

    def maybe_error(self) -> bool:
        """True when an HTTP source should return a 5xx."""
        return self._rng.random() < self.config.error_5xx_rate

    def maybe_bad_quality(self) -> bool:
        """True when a value should carry a bad-quality flag."""
        return self._rng.random() < self.config.bad_quality_rate

    # --- timestamp skew ---

    def skew_timestamp(self, ts: datetime) -> datetime:
        """Shift a timestamp by the configured source clock skew."""
        if self.config.clock_skew_seconds == 0.0:
            return ts
        return ts + timedelta(seconds=self.config.clock_skew_seconds)

    # --- latency ---

    def next_latency_ms(self) -> float:
        """Sample an injected latency in milliseconds (deterministic given seed).

        ``latency_mean_ms`` sets the typical (body) latency; ``latency_p99_ms``
        sets the magnitude of rare tail spikes. Returns 0 when latency is off.
        """
        mean = self.config.latency_mean_ms
        p99 = self.config.latency_p99_ms
        if mean <= 0.0 and p99 <= 0.0:
            return 0.0
        u = self._rng.random()
        if u >= (1.0 - _TAIL_FRACTION) and p99 > mean:
            frac = (u - (1.0 - _TAIL_FRACTION)) / _TAIL_FRACTION
            return mean + frac * (p99 - mean)
        return mean * (0.5 + self._rng.random())

    def apply_latency(self) -> float:
        """Sleep for an injected latency and return the milliseconds slept."""
        ms = self.next_latency_ms()
        if ms > 0.0:
            time.sleep(ms / 1000.0)
        return ms
