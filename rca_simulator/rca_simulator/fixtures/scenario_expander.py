"""S2.1 — scenario expander.

Turns a scenario + the reference plant into deterministic signal values that
every simulator reads. The core is :func:`value_at`, a pure function the
simulators sample on demand (PI synthesizes ranges, OPC UA/MQTT sample the
current second). :func:`expand_series` materializes a range; :func:`events_by_sink`
extracts discrete events with absolute timestamps.

Synthesis model (MVP, trend-only — see memory: simulator-scenario-realism-gap):

    value(t) = baseline.mean
             + diurnal_amplitude * sin(2π * second_of_day / 86400)
             + seeded_noise(signal, t)            # ~N(0, baseline.stddev)
             + trajectory_offset(scenario, role, t)

Determinism: the noise seed is derived from a stable string via ``hashlib`` (NOT
the builtin ``hash``, which is salted per process), so values reproduce across
calls and processes.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timedelta

from .schema import RefPlant, ScenarioEvent, SignalTrajectory

_SECONDS_PER_DAY = 86400


# ---------- trajectory ----------

def _trajectory_offset(traj: SignalTrajectory, day: float, duration_days: float) -> float:
    """Offset contributed by a trajectory at ``day`` days into the scenario.

    Before the scenario (day < 0) the offset is 0; after the end it holds the
    final value. ``step_then_growth`` is a rising step function: the offset jumps
    to each step's level once its ``at_day`` is reached.
    """
    if day <= 0:
        return 0.0
    if traj.trajectory == "constant":
        return traj.start_offset
    if traj.trajectory in ("linear_decay", "linear_growth"):
        frac = min(day / duration_days, 1.0) if duration_days > 0 else 1.0
        return traj.start_offset + (traj.end_offset - traj.start_offset) * frac
    if traj.trajectory == "step_then_growth":
        offset = 0.0
        for step in sorted(traj.steps, key=lambda s: s.at_day):
            if day >= step.at_day:
                offset = step.offset
        return offset
    raise ValueError(f"unknown trajectory kind: {traj.trajectory!r}")


# ---------- noise ----------

def _noise(signal_key: str, t: datetime, stddev: float, seed: int) -> float:
    if stddev <= 0.0:
        return 0.0
    epoch_second = int(t.timestamp())
    digest = hashlib.sha256(f"{seed}|{signal_key}|{epoch_second}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    return rng.gauss(0.0, stddev)


# ---------- core ----------

def value_at(
    rp: RefPlant,
    scenario_id: str,
    signal_key: str,
    t: datetime,
    *,
    with_noise: bool = True,
    seed: int = 0,
) -> float:
    """Value of ``signal_key`` at time ``t`` under ``scenario_id``.

    A signal is perturbed only when it belongs to the scenario's affected asset
    and has a matching trajectory; otherwise it returns its baseline (this is
    what gives scenario isolation across assets).
    """
    sig = rp.signals[signal_key]
    baseline = sig.baseline

    second_of_day = (t.hour * 3600) + (t.minute * 60) + t.second
    diurnal = baseline.diurnal_amplitude * math.sin(
        2 * math.pi * second_of_day / _SECONDS_PER_DAY
    )

    offset = 0.0
    sc = rp.scenarios[scenario_id]
    if sig.asset_ref == sc.affected_asset:
        day = (t - sc.t0).total_seconds() / _SECONDS_PER_DAY
        for traj in sc.signal_trajectories:
            if traj.role == sig.role:
                offset += _trajectory_offset(traj, day, sc.duration_days)

    noise = _noise(signal_key, t, baseline.stddev, seed) if with_noise else 0.0
    return baseline.mean + diurnal + noise + offset


def expand_series(
    rp: RefPlant,
    scenario_id: str,
    signal_key: str,
    start: datetime,
    end: datetime,
    step_seconds: int = 1,
    *,
    with_noise: bool = True,
    seed: int = 0,
) -> list[tuple[datetime, float]]:
    """Materialize ``signal_key`` over ``[start, end)`` at ``step_seconds`` spacing."""
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    out: list[tuple[datetime, float]] = []
    t = start
    delta = timedelta(seconds=step_seconds)
    while t < end:
        out.append((t, value_at(rp, scenario_id, signal_key, t,
                                with_noise=with_noise, seed=seed)))
        t += delta
    return out


def events_by_sink(
    rp: RefPlant, scenario_id: str
) -> dict[str, list[tuple[datetime, ScenarioEvent]]]:
    """Scenario events grouped by sink, each with an absolute timestamp (t0 + at_day)."""
    sc = rp.scenarios[scenario_id]
    out: dict[str, list[tuple[datetime, ScenarioEvent]]] = {}
    for ev in sc.events:
        ts = sc.t0 + timedelta(days=ev.at_day)
        out.setdefault(ev.sink, []).append((ts, ev))
    for events in out.values():
        events.sort(key=lambda pair: pair[0])
    return out


__all__ = ["value_at", "expand_series", "events_by_sink"]
