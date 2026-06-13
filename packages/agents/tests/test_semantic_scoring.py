"""Semantic document scoring (Sprint 6 WI4 D15-D17).

Covers:
1. embedding_v1 path — prior RCA ranks above datasheet via FakeToolBox vector hits.
2. Genuine rank reversal (§5.4) — keyword scorer places the keyword-dense datasheet FIRST;
   semantic scorer places the domain-language RCA FIRST.  This is the unambiguous proof that
   embedding_v1 surfaces relevant priors that keyword overlap would MISS.
3. Keyword fallback — when connection_id is None, score_method == "keyword_overlap".
4. Keyword fallback — when search_documents_by_vector returns [], score_method == "keyword_overlap".
"""
from __future__ import annotations

import copy
import json
from uuid import uuid4

from rca_contracts import (
    EvidencePackage,
    FailureModeCandidate,
    InvestigationPlan,
    PlanStep,
)

from rca_agents.gather_graph import GatherAgent, build_graph
from rca_agents.toolbox import FakeToolBox
from conftest import PROBE_RUN_ID, leg_ctx, scripted_llm

_ANOMALY_KEY = "Review these per-tag summary"
_ANOMALIES = json.dumps({"anomalies": [
    {"tag_name": "P-101A.vibration_radial", "role": "vibration_radial",
     "summary": "rose to 6.6 mm/s", "severity": "critical"},
]})


def _plan() -> InvestigationPlan:
    return InvestigationPlan(
        plan_id=uuid4(), probe_run_id=PROBE_RUN_ID, version=1,
        asset_canonical_id="asset:refinery-gc:unit-101:p-101a",
        candidate_failure_modes=[
            FailureModeCandidate(iso14224_code="ELP", name="External leakage", rank=1,
                                 confidence=0.7, reasoning="seal flush low"),
            FailureModeCandidate(iso14224_code="VIB", name="Vibration", rank=2,
                                 confidence=0.5, reasoning="vib climbing")],
        steps=[
            PlanStep(step_id=uuid4(), step_type="tag_history", description="tags",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="work_orders", description="WOs",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="documents",
                     description="docs", parameters={"query": "mechanical seal"}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="operator_logs", description="logs",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="kg_query", description="KG",
                     parameters={}, rationale="r"),
        ])


# ---------------------------------------------------------------------------
# Reversal-fixture helpers (Test 2 only — DEFAULT_FIXTURE is NOT touched)
# ---------------------------------------------------------------------------

def _reversal_plan() -> InvestigationPlan:
    """Plan whose candidate names contribute 'seal','degradation','bearing','failure' to the
    keyword term set, giving a combined set of 7 tokens:
    {'seal','degradation','bearing','failure','leak','vibration','mechanical'}.

    The datasheet title+excerpt is crafted to hit ALL 7 → keyword score 1.0.
    The RCA title+excerpt is written in domain language that hits NONE → keyword score 0.0.
    So keyword ranks  datasheet > RCA  (1.0 vs 0.0).
    The custom FakeToolBox returns vector scores RCA=0.93, datasheet=0.40.
    So semantic ranks  RCA > datasheet  (0.93 vs 0.40).
    This is the §5.4 genuine rank reversal.
    """
    return InvestigationPlan(
        plan_id=uuid4(), probe_run_id=PROBE_RUN_ID, version=1,
        asset_canonical_id="asset:refinery-gc:unit-101:p-101a",
        candidate_failure_modes=[
            FailureModeCandidate(iso14224_code="ELP", name="Seal degradation", rank=1,
                                 confidence=0.7, reasoning="face wear"),
            FailureModeCandidate(iso14224_code="VIB", name="Bearing failure", rank=2,
                                 confidence=0.5, reasoning="vib climbing")],
        steps=[
            PlanStep(step_id=uuid4(), step_type="tag_history", description="tags",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="work_orders", description="WOs",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="documents",
                     description="docs", parameters={"query": "seal degradation"}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="operator_logs", description="logs",
                     parameters={}, rationale="r"),
            PlanStep(step_id=uuid4(), step_type="kg_query", description="KG",
                     parameters={}, rationale="r"),
        ])


# Keyword-dense datasheet: title+excerpt contains every term in the 7-token set.
# Combined term set = {'seal','degradation','bearing','failure','leak','vibration','mechanical'}
# 'seal'✓ 'degradation'✓ 'bearing'✓ 'failure'✓ 'leak'✓ 'vibration'✓ 'mechanical'✓  → 7/7 = 1.0
_REVERSAL_DATASHEET = {
    "document_id": "DS-REVERSAL",
    "title": "Pump datasheet: mechanical seal bearing assembly",
    "doc_type": "datasheet",
    "excerpt": "vibration limits, leak detection, degradation thresholds, failure modes listed",
}

# Domain-language RCA: describes the failure without hitting any keyword tokens.
# None of {'seal','degradation','bearing','failure','leak','vibration','mechanical'} appear.
# → 0/7 = 0.0
_REVERSAL_RCA = {
    "document_id": "RCA-REVERSAL",
    "title": "Prior RCA: progressive face scoring on sister unit",
    "doc_type": "rca_report",
    "excerpt": (
        "progressive face scoring from inadequate barrier-fluid circulation "
        "caused elevated interface temperature and subsequent rapid face separation"
    ),
}

_REVERSAL_DOCS = [_REVERSAL_DATASHEET, _REVERSAL_RCA]


def _seed(plan: InvestigationPlan) -> dict:
    return {"agent": "gather", "plan": plan.model_dump(mode="json"), "lookback_hours": 168}


# ---------------------------------------------------------------------------
# Test 1: embedding_v1 path — prior RCA outranks datasheet
# ---------------------------------------------------------------------------
async def test_embedding_v1_ranks_prior_rca_above_datasheet():
    """FakeToolBox.search_documents_by_vector returns RCA-2025-014 with score 0.95 and
    P-101A-DS with 0.55 — gather must surface embedding_v1 and respect that ordering."""
    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=FakeToolBox())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False

    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    de = pkg.document_evidence

    assert de.score_method == "embedding_v1", (
        f"expected embedding_v1 but got {de.score_method!r}")
    assert de.documents, "expected non-empty document list"

    first_id = de.documents[0].document_id
    assert first_id == "RCA-2025-014", (
        f"prior RCA should rank first (semantic win), got {first_id!r}")
    # The prior RCA score is the 0.95 cosine score from the fake vector search
    assert de.documents[0].score == 0.95

    # Datasheet is present but second
    ids = [d.document_id for d in de.documents]
    assert "P-101A-DS" in ids
    assert ids.index("RCA-2025-014") < ids.index("P-101A-DS"), (
        "RCA must appear before the datasheet in the ranking")


# ---------------------------------------------------------------------------
# Test 2: §5.4 — GENUINE rank reversal proving semantic win over keyword scoring
# ---------------------------------------------------------------------------
async def test_semantic_win_is_genuine_rank_reversal():
    """§5.4 genuine rank reversal: keyword ranks the datasheet FIRST; semantic ranks the RCA FIRST.

    This is the unambiguous demonstration that embedding_v1 surfaces a relevant prior RCA
    that keyword-overlap scoring would MISS (the RCA text uses domain language with zero
    overlap against the keyword term set, so keyword scoring would never surface it first).

    Keyword term set (7 tokens from _reversal_plan() candidate names + hardcoded set):
        {'seal','degradation','bearing','failure','leak','vibration','mechanical'}

    _REVERSAL_DATASHEET title+excerpt contains ALL 7 tokens  → keyword score 7/7 = 1.0
    _REVERSAL_RCA title+excerpt contains NONE of them        → keyword score 0/7 = 0.0

    Custom FakeToolBox returns vector scores: RCA=0.93, datasheet=0.40
    → semantic ranks RCA first (0.93 > 0.40).

    The DEFAULT_FIXTURE is NOT touched; this test uses its own isolated documents list
    and a custom FakeToolBox subclass with an overridden search_documents_by_vector.
    """
    plan = _reversal_plan()

    # --- Assertion 1: keyword ranks DATASHEET first (it would MISS the RCA) ----------
    kw_scored, kw_method = GatherAgent._score_documents_keyword(_REVERSAL_DOCS, plan)
    assert kw_method == "keyword_overlap"

    kw_ds_score = next(d.score for d in kw_scored if d.document_id == "DS-REVERSAL")
    kw_rca_score = next(d.score for d in kw_scored if d.document_id == "RCA-REVERSAL")

    assert kw_ds_score > kw_rca_score, (
        f"keyword must rank datasheet first (DS score {kw_ds_score} must exceed "
        f"RCA score {kw_rca_score}): keyword scoring would MISS the domain-language RCA")
    assert kw_scored[0].document_id == "DS-REVERSAL", (
        "keyword scorer must place the keyword-dense datasheet first")

    # --- Assertion 2: semantic (embedding_v1) ranks RCA first (genuine reversal) -------
    class _ReversalToolBox(FakeToolBox):
        """Isolated FakeToolBox: documents list replaced with the reversal fixture;
        search_documents_by_vector returns RCA=0.93 > datasheet=0.40 (semantic win).
        DEFAULT_FIXTURE is NOT mutated."""

        def __init__(self) -> None:
            # Build a fixture from DEFAULT_FIXTURE but with the reversal docs list
            fixture = copy.deepcopy(FakeToolBox.DEFAULT_FIXTURE)
            fixture["documents"] = list(_REVERSAL_DOCS)
            super().__init__(fixture=fixture)

        async def search_documents_by_vector(self, *, connection_id, query_embedding,
                                              doc_types=None, top=5):
            # Semantic scores: the domain-language RCA is semantically closest to the
            # failure-mode query (0.93); the keyword-dense datasheet scores low (0.40).
            hits = [
                {"document_id": "RCA-REVERSAL", "doc_type": "rca_report", "score": 0.93},
                {"document_id": "DS-REVERSAL",  "doc_type": "datasheet",  "score": 0.40},
            ]
            if doc_types:
                hits = [h for h in hits if h["doc_type"] in doc_types]
            return hits[:top]

    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=_ReversalToolBox())
    leg = await agent.run_leg(graph_state=_seed(plan), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False

    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    de = pkg.document_evidence

    assert de.score_method == "embedding_v1", (
        f"expected embedding_v1 (semantic path) but got {de.score_method!r}")
    assert de.documents[0].document_id == "RCA-REVERSAL", (
        f"semantic must rank the domain-language RCA first (genuine reversal), "
        f"got {de.documents[0].document_id!r}")
    assert de.documents[0].score == 0.93

    # Confirm the datasheet is present but second (rank reversed vs keyword)
    ids = [d.document_id for d in de.documents]
    assert "DS-REVERSAL" in ids
    assert ids.index("RCA-REVERSAL") < ids.index("DS-REVERSAL"), (
        "RCA must appear before the keyword-dense datasheet — this is the reversal")


# ---------------------------------------------------------------------------
# Test 3: fallback when connection_id is None
# ---------------------------------------------------------------------------
async def test_keyword_fallback_when_no_connection_id():
    """When the documents provenance has no connection_id (e.g. doc connector not registered),
    _score_documents must fall back to keyword_overlap."""
    class _NoConnDocs(FakeToolBox):
        async def documents_for_asset(self, canonical_id, query):
            from rca_agents.toolbox import _prov
            docs = self.fixture["documents"]
            # connection_id=None simulates a connector with no registered source
            prov = _prov("document", canonical_id, "document.search_for_asset",
                         None, len(docs), self._now())
            return docs, prov

    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=_NoConnDocs())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False

    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    assert pkg.document_evidence.score_method == "keyword_overlap", (
        "no connection_id → must fall back to keyword_overlap")


# ---------------------------------------------------------------------------
# Test 4: fallback when search_documents_by_vector returns []
# ---------------------------------------------------------------------------
async def test_keyword_fallback_when_vector_search_returns_empty():
    """When search_documents_by_vector returns an empty list (e.g. no embeddings indexed yet),
    _score_documents must fall back to keyword_overlap."""
    class _EmptyVectorSearch(FakeToolBox):
        async def search_documents_by_vector(self, *, connection_id, query_embedding,
                                              doc_types=None, top=5):
            return []  # no embeddings indexed yet

    agent = build_graph()
    ctx = leg_ctx(scripted_llm({_ANOMALY_KEY: _ANOMALIES}), prompt="P-101A",
                  toolbox=_EmptyVectorSearch())
    leg = await agent.run_leg(graph_state=_seed(_plan()), hitl_response=None, ctx=ctx)
    assert leg.needs_hitl is False

    pkg = EvidencePackage.model_validate(leg.final_output["evidence_package"])
    assert pkg.document_evidence.score_method == "keyword_overlap", (
        "empty vector hits → must fall back to keyword_overlap")
    # Documents are still present (scored by keyword)
    assert pkg.document_evidence.documents
