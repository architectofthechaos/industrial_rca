"""Gather agent (Sprint 3 WI4).

Executes the approved plan through the ToolBox, lazily materializes the KG Asset layer,
runs LLM anomaly detection (3σ fallback), scores documents, and assembles the canonical
Evidence Package. HITL only when a step comes back empty/sparse (propose extending the
window). The workflow seeds the first leg's ``graph_state`` with the finalized plan.
"""
from __future__ import annotations

from typing import Any, Literal

from rca_contracts import (
    AgentLegResult,
    AssetSummary,
    CategoryCoverage,
    CoverageReport,
    DocumentEvidence,
    EvidencePackage,
    HierarchyPath,
    HitlQuestion,
    HitlResponse,
    HitlTurn,
    InvestigationPlan,
    ISO14224Context,
    Message,
    OperatorLogEvidence,
    PlanExecutionNote,
    ProvenanceEntry,
    ScoredDocument,
    TagAnomaly,
    TagEvidence,
    TokenUsage,
    WorkOrderEvidence,
    parse_canonical_id,
)

from .base import LegContext, det_uuid
from .toolbox import STEP_TYPE_TO_TOOL  # noqa: F401  (documents the G14 mapping used below)


class GatherAgent:
    async def run_leg(
        self, *, graph_state: dict | None, hitl_response: HitlResponse | None, ctx: LegContext,
    ) -> AgentLegResult:
        state: dict[str, Any] = graph_state or {}
        messages: list[Message] = []

        if hitl_response is not None and state.get("awaiting") == "scope":
            state["lookback_hours"] = int(state.get("lookback_hours", 168)) * 2
            state["awaiting"] = None
            state["window_extended"] = True
            messages.append(Message(role="user", content="engineer extended the window"))

        plan = InvestigationPlan.model_validate(state["plan"])
        lookback = int(state.get("lookback_hours", 168))

        raw, notes, provenance = await self._execute_steps(plan, ctx, lookback)
        state["raw"] = raw

        # HITL: empty tag history -> propose extending the window (once)
        if (not raw["tags"]) and not state.get("window_extended"):
            state["awaiting"] = "scope"
            state["lookback_hours"] = lookback
            turn = HitlTurn(
                turn_id=det_uuid(ctx.probe_run_id, "gather", "scope"),
                questions=[HitlQuestion(
                    question_id=det_uuid(ctx.probe_run_id, "q", "extend_window"),
                    text=f"Tag history for the last {lookback}h is empty. Extend the window?",
                    question_type="scope", required=True)],
                context_for_engineer="No tag history in the requested window.",
                asked_at=ctx.reference_time, agent_name="gather")
            return AgentLegResult(needs_hitl=True, hitl_turn=turn, graph_state=state,
                                  new_messages=messages)

        usage, llm_ids, pkg = await self._assemble(plan, ctx, raw, notes, provenance, lookback)
        state["evidence_package_id"] = str(pkg.evidence_package_id)
        messages.append(Message(role="assistant", content="assembled evidence package"))
        return AgentLegResult(
            needs_hitl=False,
            final_output={"evidence_package": pkg.model_dump(mode="json")},
            graph_state=state, new_messages=messages, new_llm_call_ids=llm_ids,
            token_usage_delta=usage)

    # ---- node: execute_plan_steps ---------------------------------------------
    async def _execute_steps(self, plan: InvestigationPlan, ctx: LegContext, lookback: int):
        raw: dict[str, Any] = {"tags": [], "work_orders": [], "documents": [],
                               "operator_logs": [], "context": None}
        notes: list[PlanExecutionNote] = []
        provenance: list[ProvenanceEntry] = []
        cid = plan.asset_canonical_id
        for step in plan.steps:
            count, status, deviation = 0, "ok", None
            try:
                if step.step_type == "tag_history":
                    tags, prov = await ctx.toolbox.tag_history(
                        cid, reference_time=ctx.reference_time, lookback_hours=lookback)
                    raw["tags"], count = tags, len(tags)
                    provenance.append(prov)
                elif step.step_type == "work_orders":
                    wos, prov = await ctx.toolbox.work_orders_for_asset(cid)
                    raw["work_orders"], count = wos, len(wos)
                    provenance.append(prov)
                elif step.step_type == "documents":
                    query = step.parameters.get("query", "failure")
                    docs, prov = await ctx.toolbox.documents_for_asset(cid, query)
                    raw["documents"], count = docs, len(docs)
                    provenance.append(prov)
                elif step.step_type == "operator_logs":
                    logs, prov = await ctx.toolbox.operator_logs_for_asset(
                        cid, reference_time=ctx.reference_time, lookback_hours=lookback)
                    raw["operator_logs"], count = logs, len(logs)
                    provenance.append(prov)
                elif step.step_type == "kg_query":
                    raw["context"] = await ctx.toolbox.get_asset_context(cid)
                    count = 1
                if count == 0:
                    status = "empty"
            except Exception as exc:  # noqa: BLE001 — a category outage shouldn't fail the probe
                status, deviation = "skipped", str(exc)[:200]
            notes.append(PlanExecutionNote(step_id=step.step_id, step_type=step.step_type,
                                           records_returned=count, status=status,
                                           deviation=deviation))
        return raw, notes, provenance

    # ---- nodes: materialize_kg, detect_anomalies, score_documents, assemble ----
    async def _assemble(self, plan: InvestigationPlan, ctx: LegContext, raw: dict,
                        notes: list[PlanExecutionNote], provenance: list[ProvenanceEntry],
                        lookback: int):
        cid = plan.asset_canonical_id
        usage = TokenUsage()
        llm_ids: list = []
        context = raw.get("context") or await ctx.toolbox.get_asset_context(cid)
        equipment_class = context.get("iso14224_class")
        if not equipment_class:
            # D1/G5: the KG-native class must resolve via MAR->KG context; no silent fallback.
            # An unresolved class is a hard error (it would otherwise orphan the asset on upsert).
            raise ValueError(
                f"no resolved KG equipment class for {cid!r} in asset context; "
                "cannot materialize the KG asset layer")
        investigated = [c.iso14224_code for c in plan.candidate_failure_modes[:3]]

        # materialize_kg — lazy Asset upsert + per-mode CAN_EXHIBIT links
        asset_meta = context.get("asset") or {}
        await ctx.toolbox.upsert_asset(
            canonical_id=cid, name=asset_meta.get("name", cid.split(":")[-1].upper()),
            iso14224_class=equipment_class, confidence=0.95, method="register",
            reference_time=ctx.reference_time)
        valid_codes = {m["code"] for m in context.get("applicable_failure_modes", [])}
        for code in investigated:
            if code in valid_codes:
                await ctx.toolbox.link_failure_mode(canonical_id=cid, failure_mode_code=code)

        anomalies, anomaly_method, a_usage, a_ids = await self._detect_anomalies(ctx, raw["tags"])
        usage = usage.merged_with(a_usage)
        llm_ids += a_ids
        scored_docs, score_method = self._score_documents(raw["documents"], plan)

        pkg = EvidencePackage(
            evidence_package_id=det_uuid(ctx.probe_run_id, "evidence"),
            probe_run_id=ctx.probe_run_id, canonical_id=cid,
            investigated_failure_modes=investigated, reference_time=ctx.reference_time,
            lookback_hours=lookback,
            asset=self._asset_summary(cid, asset_meta, equipment_class),
            location=self._location(cid, asset_meta),
            iso14224_context=ISO14224Context(
                equipment_class=equipment_class,
                applicable_failure_modes=context.get("applicable_failure_modes", [])),
            tag_evidence=TagEvidence(tags=raw["tags"], anomalies=anomalies,
                                     anomaly_method=anomaly_method),
            work_order_evidence=WorkOrderEvidence(work_orders=raw["work_orders"]),
            document_evidence=DocumentEvidence(documents=scored_docs, score_method=score_method),
            operator_log_evidence=OperatorLogEvidence(entries=raw["operator_logs"]),
            investigation_plan=plan, plan_execution_notes=notes,
            coverage=self._coverage(raw, notes), provenance=provenance,
            assembled_at=ctx.reference_time)
        return usage, llm_ids, pkg

    async def _detect_anomalies(self, ctx: LegContext, tags: list[dict]):
        if not tags:
            return [], "rule:3sigma", TokenUsage(), []
        try:
            resp = await ctx.llm.complete(
                "detect_tag_anomalies", "v1",
                {"tag_summaries": tags, "reference_time": ctx.reference_time.isoformat()},
                correlation_id=ctx.correlation_id, probe_run_id=ctx.probe_run_id,
                budget=ctx.budget, replay_from_cache=ctx.replay_from_cache)
            structured = resp.structured
            if structured and structured.get("anomalies"):
                anomalies = [TagAnomaly(tag_name=a["tag_name"], role=a.get("role"),
                                        summary=a["summary"], severity=a.get("severity"))
                             for a in structured["anomalies"]]
                return (anomalies, "llm_v1",
                        TokenUsage(input_tokens=resp.input_tokens,
                                   output_tokens=resp.output_tokens), [resp.llm_call_id])
        except Exception:  # noqa: BLE001 — fall back to the deterministic rule
            pass
        return self._rule_3sigma(tags), "rule:3sigma", TokenUsage(), []

    @staticmethod
    def _rule_3sigma(tags: list[dict]) -> list[TagAnomaly]:
        # Fixture tags carry a precomputed severity + mean/max; flag elevated/critical, or a
        # max well above the mean (a stand-in for a 3σ exceedance on real series).
        out = []
        for t in tags:
            sev = t.get("severity")
            elevated = sev in {"elevated", "critical"} or (
                t.get("mean") and t.get("max") and t["max"] > 1.5 * t["mean"])
            if elevated:
                out.append(TagAnomaly(tag_name=t["tag_name"], role=t.get("role"),
                                      summary=t.get("summary", "out-of-band"),
                                      severity=sev or "elevated"))
        return out

    @staticmethod
    def _score_documents(
        docs: list[dict], plan: InvestigationPlan,
    ) -> tuple[list[ScoredDocument], Literal["embedding_v1", "keyword_overlap"]]:
        terms = set()
        for c in plan.candidate_failure_modes:
            terms.update(c.name.lower().split())
        terms.update({"seal", "leak", "vibration", "bearing", "mechanical"})
        scored = []
        for d in docs:
            text = f"{d.get('title','')} {d.get('excerpt','')}".lower()
            overlap = sum(1 for term in terms if term in text)
            score = overlap / max(len(terms), 1)
            scored.append(ScoredDocument(document_id=d["document_id"], title=d.get("title", ""),
                                         doc_type=d.get("doc_type"), score=round(score, 4),
                                         excerpt=d.get("excerpt")))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored, "keyword_overlap"

    @staticmethod
    def _asset_summary(cid: str, meta: dict, equipment_class: str) -> AssetSummary:
        return AssetSummary(
            canonical_id=cid, name=meta.get("name", cid.split(":")[-1].upper()),
            iso14224_class=equipment_class, service=meta.get("service"),
            criticality=meta.get("criticality"), manufacturer=meta.get("manufacturer"),
            model=meta.get("model"))

    @staticmethod
    def _location(cid: str, meta: dict) -> HierarchyPath:
        parts = parse_canonical_id(cid)
        return HierarchyPath(plant_id=parts.plant_id, unit=meta.get("unit", parts.unit_slug))

    @staticmethod
    def _coverage(raw: dict, notes: list[PlanExecutionNote]) -> CoverageReport:
        skipped = {n.step_type: n for n in notes if n.status == "skipped"}

        def cov(key: str, step_type: str) -> CategoryCoverage:
            if step_type in skipped:
                return CategoryCoverage(status="skipped:connection_unhealthy",
                                        note=skipped[step_type].deviation)
            n = len(raw.get(key, []))
            return CategoryCoverage(status="ok" if n else "empty", record_count=n)

        return CoverageReport(
            historian=cov("tags", "tag_history"), cmms=cov("work_orders", "work_orders"),
            documents=cov("documents", "documents"),
            operator_log=cov("operator_logs", "operator_logs"))


def build_graph() -> GatherAgent:
    return GatherAgent()


__all__ = ["GatherAgent", "build_graph"]
