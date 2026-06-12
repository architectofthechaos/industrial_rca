"""Postgres probe-runs + probe-memory repos (Sprint 4 WI5).

Behaviorally equivalent to the in-memory impls in ``repos.py``; the tables/ORM
(``rca_mar.models.ProbeRun`` / ``ProbeMemory``) + migration 0005 already exist, so these only
read/write. ``create_run`` is idempotent (``on_conflict_do_nothing`` — Temporal activity retry).
Evidence-package + conclusion Pg repos land in a later task.

``probe_memory.last_updated_at`` is NOT NULL with no server default and is NOT part of the
deterministic agent state the in-memory repo tracks (it never stores a timestamp). It is a UI
freshness marker, so each write sets it via ``func.now()`` (write-side, not derived from
reference_time) — this introduces no nondeterminism into the agent/probe state itself.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from rca_contracts import ProbeRunStatus
from rca_mar.config import make_engine, make_session_factory
from rca_mar.models import ProbeMemory, ProbeRun


# ------------------------------------------------------------------- probe_runs
class PgProbeRunsRepo:
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def create_run(self, *, probe_run_id: UUID, workflow_id: str, plant_id: str,
                         prompt: str, reference_time: datetime, requested_by: str,
                         started_at: datetime) -> None:
        values = {
            "probe_run_id": probe_run_id, "workflow_id": workflow_id, "plant_id": plant_id,
            "prompt": prompt, "reference_time": reference_time, "requested_by": requested_by,
            "status": ProbeRunStatus.RUNNING.value, "phase": "planning",
            "final_canonical_id": None, "token_usage": {}, "errors": [],
            "started_at": started_at, "completed_at": None,
        }
        async with self._sf() as s, s.begin():
            stmt = pg_insert(ProbeRun).values(**values).on_conflict_do_nothing(
                index_elements=[ProbeRun.probe_run_id])
            await s.execute(stmt)

    async def update_status(self, probe_run_id: UUID, *, status: str, phase: str | None = None,
                            final_canonical_id: str | None = None,
                            token_usage: dict | None = None,
                            errors: list[dict] | None = None,
                            completed_at: datetime | None = None) -> None:
        async with self._sf() as s, s.begin():
            run = await s.get(ProbeRun, probe_run_id)
            if run is None:
                raise KeyError(probe_run_id)
            run.status = status
            if phase is not None:
                run.phase = phase
            if final_canonical_id is not None:
                run.final_canonical_id = final_canonical_id
            if token_usage is not None:
                run.token_usage = token_usage
            if errors is not None:
                run.errors = errors
            if completed_at is not None:
                run.completed_at = completed_at

    async def get_run(self, probe_run_id: UUID) -> dict | None:
        async with self._sf() as s:
            run = await s.get(ProbeRun, probe_run_id)
            if run is None:
                return None
            return {c.name: getattr(run, c.name) for c in ProbeRun.__table__.columns}


# ------------------------------------------------------------------- probe_memory
class PgProbeMemoryRepo:
    def __init__(self, session_factory: Any = None) -> None:
        self._sf = session_factory or make_session_factory(make_engine())

    async def _load_or_init(self, s: Any, probe_run_id: UUID) -> ProbeMemory:
        row = await s.get(ProbeMemory, probe_run_id)
        if row is None:
            row = ProbeMemory(
                probe_run_id=probe_run_id, conversation=[], current_plan=None,
                plan_history=[], working_knowledge={}, agent_scratchpad=[],
                token_usage={}, last_updated_at=func.now())
            s.add(row)
        return row

    async def snapshot(self, probe_run_id: UUID, snapshot: dict) -> None:
        async with self._sf() as s, s.begin():
            row = await self._load_or_init(s, probe_run_id)
            for key in ("current_plan", "working_knowledge", "token_usage"):
                if key in snapshot:
                    setattr(row, key, snapshot[key])
            if snapshot.get("plan_version_added") is not None:
                row.plan_history = [*(row.plan_history or []), snapshot["plan_version_added"]]
            new_messages = snapshot.get("new_messages", [])
            if new_messages:
                row.agent_scratchpad = [*(row.agent_scratchpad or []), *new_messages]
            row.last_updated_at = func.now()

    async def get(self, probe_run_id: UUID) -> dict | None:
        async with self._sf() as s:
            row = (await s.execute(
                select(ProbeMemory).where(
                    ProbeMemory.probe_run_id == probe_run_id))).scalar_one_or_none()
            if row is None:
                return None
            return {c.name: getattr(row, c.name) for c in ProbeMemory.__table__.columns}

    async def append_turn(self, probe_run_id: UUID, turn: dict) -> None:
        await self._append_conversation(probe_run_id, {"kind": "turn", **turn})

    async def append_response(self, probe_run_id: UUID, response: dict) -> None:
        await self._append_conversation(probe_run_id, {"kind": "response", **response})

    async def _append_conversation(self, probe_run_id: UUID, entry: dict) -> None:
        async with self._sf() as s, s.begin():
            row = await self._load_or_init(s, probe_run_id)
            row.conversation = [*(row.conversation or []), entry]
            row.last_updated_at = func.now()


__all__ = ["PgProbeRunsRepo", "PgProbeMemoryRepo"]
