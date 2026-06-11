"""Probe persistence ports (Sprint 3 WI2/WI4/WI5) — Protocols + in-memory impls.

These back the probe data layer: ``probe_runs`` (status lifecycle, mirrors onboarding_runs,
G17/G18), ``probe_memory`` (the 3-layer model's Postgres UI snapshot, §2.4), and the
``evidence_packages`` / ``rca_conclusions`` stores. In-memory impls make the workflow fully
hermetic; Postgres impls (rca_mar) write the real tables.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from rca_contracts import EvidencePackage, ProbeRunStatus, RcaConclusion


# ------------------------------------------------------------------- probe_runs
class ProbeRunsRepo(Protocol):
    async def create_run(self, *, probe_run_id: UUID, workflow_id: str, plant_id: str,
                         prompt: str, reference_time: datetime, requested_by: str,
                         started_at: datetime) -> None: ...
    async def update_status(self, probe_run_id: UUID, *, status: str, phase: str | None = None,
                            final_canonical_id: str | None = None,
                            token_usage: dict | None = None,
                            errors: list[dict] | None = None,
                            completed_at: datetime | None = None) -> None: ...
    async def get_run(self, probe_run_id: UUID) -> dict | None: ...


class InMemoryProbeRunsRepo:
    def __init__(self) -> None:
        self.runs: dict[UUID, dict[str, Any]] = {}

    async def create_run(self, *, probe_run_id: UUID, workflow_id: str, plant_id: str,
                         prompt: str, reference_time: datetime, requested_by: str,
                         started_at: datetime) -> None:
        self.runs.setdefault(probe_run_id, {
            "probe_run_id": str(probe_run_id), "workflow_id": workflow_id, "plant_id": plant_id,
            "prompt": prompt, "reference_time": reference_time, "requested_by": requested_by,
            "status": ProbeRunStatus.RUNNING.value, "phase": "planning",
            "final_canonical_id": None, "token_usage": {}, "errors": [],
            "started_at": started_at, "completed_at": None})

    async def update_status(self, probe_run_id: UUID, *, status: str, phase: str | None = None,
                            final_canonical_id: str | None = None,
                            token_usage: dict | None = None,
                            errors: list[dict] | None = None,
                            completed_at: datetime | None = None) -> None:
        run = self.runs[probe_run_id]
        run["status"] = status
        if phase is not None:
            run["phase"] = phase
        if final_canonical_id is not None:
            run["final_canonical_id"] = final_canonical_id
        if token_usage is not None:
            run["token_usage"] = token_usage
        if errors is not None:
            run["errors"] = errors
        if completed_at is not None:
            run["completed_at"] = completed_at

    async def get_run(self, probe_run_id: UUID) -> dict | None:
        run = self.runs.get(probe_run_id)
        return dict(run) if run is not None else None


# ------------------------------------------------------------------- probe_memory
class ProbeMemoryRepo(Protocol):
    async def snapshot(self, probe_run_id: UUID, snapshot: dict) -> None: ...
    async def get(self, probe_run_id: UUID) -> dict | None: ...
    async def append_turn(self, probe_run_id: UUID, turn: dict) -> None: ...
    async def append_response(self, probe_run_id: UUID, response: dict) -> None: ...


class InMemoryProbeMemoryRepo:
    def __init__(self) -> None:
        self.memory: dict[UUID, dict[str, Any]] = {}

    def _row(self, probe_run_id: UUID) -> dict[str, Any]:
        return self.memory.setdefault(probe_run_id, {
            "probe_run_id": str(probe_run_id), "conversation": [], "current_plan": None,
            "plan_history": [], "working_knowledge": {}, "agent_scratchpad": [],
            "token_usage": {}})

    async def snapshot(self, probe_run_id: UUID, snapshot: dict) -> None:
        row = self._row(probe_run_id)
        for key in ("current_plan", "working_knowledge", "token_usage"):
            if key in snapshot:
                row[key] = snapshot[key]
        if snapshot.get("plan_version_added") is not None:
            row["plan_history"].append(snapshot["plan_version_added"])
        for msg in snapshot.get("new_messages", []):
            row["agent_scratchpad"].append(msg)

    async def get(self, probe_run_id: UUID) -> dict | None:
        row = self.memory.get(probe_run_id)
        return dict(row) if row is not None else None

    async def append_turn(self, probe_run_id: UUID, turn: dict) -> None:
        self._row(probe_run_id)["conversation"].append({"kind": "turn", **turn})

    async def append_response(self, probe_run_id: UUID, response: dict) -> None:
        self._row(probe_run_id)["conversation"].append({"kind": "response", **response})


# ------------------------------------------------------------------- evidence / conclusions
class EvidencePackageRepo(Protocol):
    async def put(self, package: EvidencePackage) -> None: ...
    async def get(self, evidence_package_id: UUID) -> EvidencePackage | None: ...
    async def get_for_probe(self, probe_run_id: UUID) -> EvidencePackage | None: ...


class InMemoryEvidencePackageRepo:
    def __init__(self) -> None:
        self.packages: dict[UUID, EvidencePackage] = {}

    async def put(self, package: EvidencePackage) -> None:
        self.packages[package.evidence_package_id] = package

    async def get(self, evidence_package_id: UUID) -> EvidencePackage | None:
        return self.packages.get(evidence_package_id)

    async def get_for_probe(self, probe_run_id: UUID) -> EvidencePackage | None:
        for pkg in self.packages.values():
            if pkg.probe_run_id == probe_run_id:
                return pkg
        return None


class RcaConclusionRepo(Protocol):
    async def put(self, conclusion: RcaConclusion, *, status: str) -> None: ...
    async def get(self, conclusion_id: UUID) -> RcaConclusion | None: ...
    async def get_for_probe(self, probe_run_id: UUID) -> RcaConclusion | None: ...


class InMemoryRcaConclusionRepo:
    def __init__(self) -> None:
        self.conclusions: dict[UUID, RcaConclusion] = {}
        self.status: dict[UUID, str] = {}

    async def put(self, conclusion: RcaConclusion, *, status: str) -> None:
        self.conclusions[conclusion.conclusion_id] = conclusion
        self.status[conclusion.conclusion_id] = status

    async def get(self, conclusion_id: UUID) -> RcaConclusion | None:
        return self.conclusions.get(conclusion_id)

    async def get_for_probe(self, probe_run_id: UUID) -> RcaConclusion | None:
        latest = None
        for c in self.conclusions.values():
            if c.probe_run_id == probe_run_id:
                latest = c
        return latest


__all__ = [
    "ProbeRunsRepo", "InMemoryProbeRunsRepo", "ProbeMemoryRepo", "InMemoryProbeMemoryRepo",
    "EvidencePackageRepo", "InMemoryEvidencePackageRepo", "RcaConclusionRepo",
    "InMemoryRcaConclusionRepo",
]
