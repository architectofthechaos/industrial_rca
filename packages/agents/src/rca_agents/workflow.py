"""ProbeWorkflow (Sprint 3) — one Temporal workflow = one end-to-end probe.

Orchestrates planning -> gather -> RCA agent leg-loops (each leg an activity; HITL via a
``hitl_response`` signal released by ``wait_condition``, the G20 seam) then the deterministic
close phase (persist HistoricalFailureEvent + follow-up WO). Determinism: ``workflow.uuid4`` for
probe_run_id, ``workflow.now()`` frozen once into ``reference_time`` and threaded into every
activity + LLM call (risk #8). LangGraph never signals Temporal — only the FastAPI handler does.
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rca_contracts import HitlResponse, ProbeRunStatus, TokenUsage

    from .activities import (
        create_followup_wo,
        finalize_probe_run,
        init_probe_run,
        persist_conclusion_to_kg,
        run_agent_leg,
    )
    from .config import DEFAULT_PLANT_ID
    from .models import (
        CreateWoInput,
        FinalizeInput,
        InitProbeInput,
        PersistConclusionInput,
        ProbeResult,
        ProbeWorkflowInput,
        RunLegInput,
    )
    from rca_contracts import TokenBudget

_LEG_TIMEOUT = timedelta(minutes=5)
_LEG_RETRY = RetryPolicy(maximum_attempts=1)        # legs aren't auto-retried (avoid double LLM)
_CLOSE_TIMEOUT = timedelta(minutes=2)
_CLOSE_RETRY = RetryPolicy(maximum_attempts=3)      # close activities are idempotent
_HITL_TIMEOUT = timedelta(days=7)                   # engineer has a week to respond


@workflow.defn
class ProbeWorkflow:
    def __init__(self) -> None:
        self._hitl_response: HitlResponse | None = None
        self._pending_turn: dict | None = None
        self._status: str = ProbeRunStatus.RUNNING.value
        self._phase: str = "init"
        self._cum_usage = TokenUsage()

    @workflow.signal
    async def hitl_response(self, response: HitlResponse) -> None:
        self._hitl_response = response

    @workflow.query
    def pending_hitl_turn(self) -> dict | None:
        return self._pending_turn

    @workflow.query
    def status(self) -> dict:
        return {"status": self._status, "phase": self._phase}

    @workflow.run
    async def run(self, inp: ProbeWorkflowInput) -> ProbeResult:
        probe_run_id = str(workflow.uuid4())
        workflow_id = workflow.info().workflow_id
        started_at = workflow.now()
        reference_time = inp.reference_time or started_at
        plant_id = inp.plant_id or DEFAULT_PLANT_ID
        self._probe_run_id = probe_run_id
        self._correlation_id = f"probe:{probe_run_id}"
        self._reference_time = reference_time
        self._plant_id = plant_id
        self._prompt = inp.prompt
        self._requested_by = inp.requested_by
        self._limits = (inp.input_tokens_limit, inp.output_tokens_limit)

        await workflow.execute_activity(
            init_probe_run, InitProbeInput(
                probe_run_id=probe_run_id, workflow_id=workflow_id, plant_id=plant_id,
                prompt=inp.prompt, reference_time=reference_time, requested_by=inp.requested_by,
                started_at=started_at),
            start_to_close_timeout=_CLOSE_TIMEOUT, retry_policy=_CLOSE_RETRY)

        # ---- PLANNING ----
        self._status = self._phase = ProbeRunStatus.PLANNING.value
        planning = await self._run_agent("planning", None)
        if planning.final_output and planning.final_output.get("status") == "planning_aborted":
            return await self._finalize(probe_run_id, plant_id, None,
                                        ProbeRunStatus.PLANNING_ABORTED.value, started_at)
        plan = planning.final_output["plan"]
        canonical_id = plan["asset_canonical_id"]
        lookback = next((s["parameters"].get("lookback_hours") for s in plan["steps"]
                         if s["step_type"] == "tag_history" and s["parameters"].get(
                             "lookback_hours")), 168)

        # ---- GATHER ----
        self._status = self._phase = ProbeRunStatus.GATHERING.value
        gather = await self._run_agent("gather", {"agent": "gather", "plan": plan,
                                                  "lookback_hours": lookback})
        evidence_package = gather.final_output["evidence_package"]

        # ---- RCA ----
        self._status = self._phase = ProbeRunStatus.ANALYZING.value
        rca = await self._run_agent("rca", {"agent": "rca",
                                            "evidence_package": evidence_package})
        conclusion = rca.final_output["conclusion"]
        approval = conclusion.get("engineer_approval_status")
        actions_approved = bool(rca.final_output.get("actions_approved"))

        # ---- CLOSE (WI6) ----
        if approval in ("approved", "approved_with_edits"):
            return await self._close(probe_run_id, plant_id, canonical_id, conclusion,
                                     actions_approved, reference_time, inp.requested_by,
                                     started_at)
        return await self._finalize(probe_run_id, plant_id, canonical_id,
                                    ProbeRunStatus.CONCLUSION_REJECTED.value, started_at,
                                    conclusion_id=conclusion.get("conclusion_id"))

    # ---- leg loop (the HITL bridge) -------------------------------------------
    async def _run_agent(self, agent_name: str, seed_state: dict | None):
        graph_state = seed_state
        hitl_input: HitlResponse | None = None
        while True:
            in_used, out_used = self._cum_usage.input_tokens, self._cum_usage.output_tokens
            budget = TokenBudget(
                input_tokens_limit=self._limits[0], output_tokens_limit=self._limits[1],
                input_used=in_used, output_used=out_used)
            leg = await workflow.execute_activity(
                run_agent_leg, RunLegInput(
                    probe_run_id=self._probe_run_id, agent_name=agent_name,
                    graph_state=graph_state, hitl_response=hitl_input,
                    correlation_id=self._correlation_id, budget=budget,
                    reference_time=self._reference_time, plant_id=self._plant_id,
                    prompt=self._prompt, requested_by=self._requested_by),
                start_to_close_timeout=_LEG_TIMEOUT, retry_policy=_LEG_RETRY)
            self._cum_usage = self._cum_usage.merged_with(leg.token_usage_delta)
            graph_state = leg.graph_state
            if not leg.needs_hitl:
                self._pending_turn = None
                return leg
            self._pending_turn = leg.hitl_turn.model_dump(mode="json") if leg.hitl_turn else None
            await workflow.wait_condition(lambda: self._hitl_response is not None,
                                          timeout=_HITL_TIMEOUT)
            hitl_input = self._hitl_response
            self._hitl_response = None

    # ---- close + finalize ------------------------------------------------------
    async def _close(self, probe_run_id, plant_id, canonical_id, conclusion, actions_approved,
                     reference_time, requested_by, started_at) -> ProbeResult:
        self._status = self._phase = ProbeRunStatus.AWAITING_REVIEW.value
        event_id = await workflow.execute_activity(
            persist_conclusion_to_kg,
            PersistConclusionInput(conclusion=conclusion, reference_time=reference_time),
            start_to_close_timeout=_CLOSE_TIMEOUT, retry_policy=_CLOSE_RETRY)

        followup_wo_id: str | None = None
        wo_status: str | None = None
        if conclusion.get("recommended_actions") and actions_approved:
            try:
                wo = await workflow.execute_activity(
                    create_followup_wo, CreateWoInput(
                        conclusion=conclusion, failure_event_id=event_id,
                        requested_by=requested_by, reference_time=reference_time),
                    start_to_close_timeout=_CLOSE_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2))
                followup_wo_id = wo.get("work_order_id")
                wo_status = "created"
            except Exception as exc:  # noqa: BLE001 — WO failure must NOT fail the probe (§6.3)
                wo_status = "failed"
                workflow.logger.warning(f"follow-up WO creation failed: {exc}")

        result = await self._finalize(
            probe_run_id, plant_id, canonical_id, ProbeRunStatus.COMPLETED.value, started_at,
            conclusion_id=conclusion.get("conclusion_id"))
        return result.model_copy(update={
            "failure_event_id": event_id, "followup_wo_id": followup_wo_id,
            "wo_creation_status": wo_status})

    async def _finalize(self, probe_run_id, plant_id, canonical_id, status, started_at, *,
                        conclusion_id: str | None = None) -> ProbeResult:
        self._status = status
        completed_at = workflow.now()
        await workflow.execute_activity(
            finalize_probe_run, FinalizeInput(
                probe_run_id=probe_run_id, status=status, final_canonical_id=canonical_id,
                token_usage=self._cum_usage.model_dump(), completed_at=completed_at),
            start_to_close_timeout=_CLOSE_TIMEOUT, retry_policy=_CLOSE_RETRY)
        return ProbeResult(
            probe_run_id=probe_run_id, workflow_id=workflow.info().workflow_id, status=status,
            canonical_id=canonical_id, conclusion_id=conclusion_id,
            token_usage=self._cum_usage.model_dump())


__all__ = ["ProbeWorkflow"]
