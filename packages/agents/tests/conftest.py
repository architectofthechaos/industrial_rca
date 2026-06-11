"""Shared hermetic fixtures for the agent tests: a scripted LLM client + fake toolbox,
wired with the packaged prompt registry. No network, no SDK, no Temporal."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from rca_contracts import TokenBudget
from rca_llm import InMemoryResponseCache, LLMClientImpl, default_registry
from rca_llm.testing import HashEmbeddingTransport, ScriptedCompletionTransport

from rca_agents.base import LegContext
from rca_agents.toolbox import FakeToolBox

REF_TIME = datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc)
PROBE_RUN_ID = UUID("0190d3c9-0000-7000-8000-00000000a001")
P101A = "asset:refinery-gc:unit-101:p-101a"


def scripted_llm(responses: dict[str, str]) -> LLMClientImpl:
    return LLMClientImpl(
        registry=default_registry(),
        transport=ScriptedCompletionTransport(responses),
        embedding_transport=HashEmbeddingTransport(dim=16),
        cache=InMemoryResponseCache())


def leg_ctx(llm, *, prompt: str, toolbox: FakeToolBox | None = None,
            plant_id: str = "refinery-gc", probe_run_id: UUID = PROBE_RUN_ID) -> LegContext:
    return LegContext(
        probe_run_id=probe_run_id, correlation_id="corr-test", reference_time=REF_TIME,
        plant_id=plant_id, prompt=prompt, requested_by="eng@deepiq.com", llm=llm,
        toolbox=toolbox or FakeToolBox(), budget=TokenBudget(input_tokens_limit=10_000_000,
                                                             output_tokens_limit=10_000_000))


# --- canonical scripted LLM responses for the P-101A seal-leak scenario ---------
def j(obj) -> str:
    return json.dumps(obj)


PLANNING_RESPONSES_CLEAR = {
    "planning agent for an industrial": j({
        "asset_candidates": [{"canonical_id": P101A, "confidence": 0.95}],
        "suspected_symptoms": ["vibration climbing", "discharge pressure dropping"],
        "time_window_hours": 168, "asset_confidence": 0.95}),
    "Rank the candidate ISO 14224": j({"candidates": [
        {"iso14224_code": "ELP", "name": "External leakage process medium", "rank": 1,
         "confidence": 0.7, "reasoning": "seal flush flow declining"},
        {"iso14224_code": "VIB", "name": "Vibration", "rank": 2, "confidence": 0.5,
         "reasoning": "radial vibration climbing"}]}),
    "Draft an opinionated": j({"steps": [
        {"step_type": "tag_history", "description": "Pull vibration + seal flush trends",
         "parameters": {"roles": ["vibration_radial", "seal_flush_flow"]},
         "rationale": "discriminate seal failure from imbalance"},
        {"step_type": "work_orders", "description": "Recent work orders",
         "parameters": {}, "rationale": "maintenance history"},
        {"step_type": "documents", "description": "Search mechanical-seal documents",
         "parameters": {"query": "mechanical seal"}, "rationale": "design + prior RCA"}]}),
}

PLANNING_RESPONSES_AMBIGUOUS = {
    "planning agent for an industrial": j({
        "asset_candidates": [
            {"canonical_id": "asset:refinery-gc:unit-101:p-101a", "confidence": 0.5},
            {"canonical_id": "asset:refinery-gc:unit-101:p-101b", "confidence": 0.45}],
        "suspected_symptoms": ["noisy"], "time_window_hours": 168, "asset_confidence": 0.5}),
    "Rank the candidate ISO 14224": PLANNING_RESPONSES_CLEAR["Rank the candidate ISO 14224"],
    "Draft an opinionated": PLANNING_RESPONSES_CLEAR["Draft an opinionated"],
}
