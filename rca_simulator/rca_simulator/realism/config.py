"""S2.8 — realism configuration parsed from env vars (per SPEC-007)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

ENV_KEYS = {
    "clock_skew_seconds": "SIM_CLOCK_SKEW_SECONDS",
    "drop_rate": "SIM_DROP_RATE",
    "bad_quality_rate": "SIM_BAD_QUALITY_RATE",
    "error_5xx_rate": "SIM_5XX_RATE",
    "latency_mean_ms": "SIM_LATENCY_MEAN_MS",
    "latency_p99_ms": "SIM_LATENCY_P99_MS",
}


@dataclass(frozen=True)
class RealismConfig:
    """Source-side realism knobs. Defaults are a clean no-op."""

    clock_skew_seconds: float = 0.0
    drop_rate: float = 0.0
    bad_quality_rate: float = 0.0
    error_5xx_rate: float = 0.0
    latency_mean_ms: float = 0.0
    latency_p99_ms: float = 0.0

    def __post_init__(self) -> None:
        for name in ("drop_rate", "bad_quality_rate", "error_5xx_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0.0, 1.0], got {value}")
        for name in ("latency_mean_ms", "latency_p99_ms"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be >= 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RealismConfig":
        source = os.environ if env is None else env
        kwargs = {
            field: float(source[key])
            for field, key in ENV_KEYS.items()
            if key in source
        }
        return cls(**kwargs)
