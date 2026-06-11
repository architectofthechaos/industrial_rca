"""OnboardingRunsRepo — persistence for `onboarding_runs` (Sprint 2b §2.5).

The workflow writes a row at start (status='running') and updates it on termination
('completed' | 'failed'). ``PostgresOnboardingRunsRepo`` rides the MAR engine/session
factory (onboarding_runs lives in the MAR Alembic chain, migration 0004) and uses the
`OnboardingRun` ORM model. ``InMemoryOnboardingRunsRepo`` mirrors the same protocol for
hermetic tests and for the negative-trigger assertion (its dict stays empty unless the
onboarding workflow actually runs).

Runs are addressed by a string ``run_id`` (the workflow mints it via ``workflow.uuid4()``
and passes it as a str through Temporal payloads); the PG impl coerces to/from UUID.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from rca_mar.models import OnboardingRun


@dataclass
class RunRecord:
    """A row of `onboarding_runs` as plain data (JSON-friendly for the API)."""
    run_id: str
    workflow_id: str
    plant_id: str
    status: str
    started_at: datetime
    connection_ids: list[str] | None = None
    completed_at: datetime | None = None
    per_category_results: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "workflow_id": self.workflow_id, "plant_id": self.plant_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "connection_ids": self.connection_ids,
            "per_category_results": self.per_category_results,
            "counts": self.counts, "errors": self.errors,
        }


class OnboardingRunsRepo(Protocol):
    async def create_run(self, run_id: str, workflow_id: str, plant_id: str,
                         connection_ids: list[str] | None, started_at: datetime) -> None: ...
    async def complete_run(self, run_id: str, status: str,
                           per_category_results: dict[str, str], counts: dict[str, int],
                           errors: list[dict], completed_at: datetime) -> None: ...
    async def get_run(self, run_id: str) -> RunRecord | None: ...
    async def get_run_by_workflow_id(self, workflow_id: str) -> RunRecord | None: ...
    async def list_runs(self, *, plant_id: str | None = None, status: str | None = None,
                        limit: int = 50) -> list[RunRecord]: ...


def _row_to_record(r: OnboardingRun) -> RunRecord:
    return RunRecord(
        run_id=str(r.run_id), workflow_id=r.workflow_id, plant_id=r.plant_id, status=r.status,
        started_at=r.started_at, connection_ids=r.connection_ids, completed_at=r.completed_at,
        per_category_results=r.per_category_results or {}, counts=r.counts or {},
        errors=r.errors or [])


class PostgresOnboardingRunsRepo:
    """OnboardingRunsRepo over the MAR async session factory."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def create_run(self, run_id, workflow_id, plant_id, connection_ids, started_at):
        async with self._sf() as s, s.begin():
            # Idempotent: a workflow replay must not duplicate the start row (run_id is the PK,
            # minted deterministically per workflow run), so ON CONFLICT DO NOTHING.
            stmt = pg_insert(OnboardingRun).values(
                run_id=UUID(run_id), workflow_id=workflow_id, plant_id=plant_id,
                connection_ids=connection_ids, status="running", started_at=started_at,
            ).on_conflict_do_nothing(index_elements=[OnboardingRun.run_id])
            await s.execute(stmt)

    async def complete_run(self, run_id, status, per_category_results, counts, errors,
                           completed_at):
        async with self._sf() as s, s.begin():
            from sqlalchemy import update
            await s.execute(
                update(OnboardingRun)
                .where(OnboardingRun.run_id == UUID(run_id))
                .values(status=status, per_category_results=per_category_results,
                        counts=counts, errors=errors, completed_at=completed_at))

    async def get_run(self, run_id):
        async with self._sf() as s:
            try:
                rid = UUID(run_id)
            except ValueError:
                return None
            q = select(OnboardingRun).where(OnboardingRun.run_id == rid)
            row = (await s.execute(q)).scalar_one_or_none()
            return _row_to_record(row) if row else None

    async def get_run_by_workflow_id(self, workflow_id):
        async with self._sf() as s:
            q = select(OnboardingRun).where(OnboardingRun.workflow_id == workflow_id)
            row = (await s.execute(q)).scalar_one_or_none()
            return _row_to_record(row) if row else None

    async def list_runs(self, *, plant_id=None, status=None, limit=50):
        async with self._sf() as s:
            q = select(OnboardingRun)
            if plant_id is not None:
                q = q.where(OnboardingRun.plant_id == plant_id)
            if status is not None:
                q = q.where(OnboardingRun.status == status)
            q = q.order_by(OnboardingRun.started_at.desc()).limit(limit)
            return [_row_to_record(r) for r in (await s.execute(q)).scalars()]


class InMemoryOnboardingRunsRepo:
    """Hermetic OnboardingRunsRepo: runs keyed by run_id."""

    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}

    async def create_run(self, run_id, workflow_id, plant_id, connection_ids, started_at):
        if run_id in self.runs:
            return  # idempotent start (mirror PG ON CONFLICT DO NOTHING)
        self.runs[run_id] = RunRecord(
            run_id=run_id, workflow_id=workflow_id, plant_id=plant_id, status="running",
            started_at=started_at, connection_ids=connection_ids)

    async def complete_run(self, run_id, status, per_category_results, counts, errors,
                           completed_at):
        rec = self.runs.get(run_id)
        if rec is None:
            return
        rec.status = status
        rec.per_category_results = per_category_results
        rec.counts = counts
        rec.errors = errors
        rec.completed_at = completed_at

    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def get_run_by_workflow_id(self, workflow_id):
        return next((r for r in self.runs.values() if r.workflow_id == workflow_id), None)

    async def list_runs(self, *, plant_id=None, status=None, limit=50):
        out = [r for r in self.runs.values()
               if (plant_id is None or r.plant_id == plant_id)
               and (status is None or r.status == status)]
        out.sort(key=lambda r: r.started_at, reverse=True)
        return out[:limit]


__all__ = ["RunRecord", "OnboardingRunsRepo", "PostgresOnboardingRunsRepo",
           "InMemoryOnboardingRunsRepo"]
