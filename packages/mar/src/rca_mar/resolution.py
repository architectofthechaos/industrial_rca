"""The 4-step asset-resolution algorithm (SPEC-011). Pure logic over an AssetRepository.

Resolution-method vocabulary (Phase 1 spec §2.4, amended Sprint 2a §1.5) —
reported in AssetResolution.mapping_source (== spec `resolution_method`):
  - 'exact_match'  active-alias short-circuit (step 1)
  - 'cross_walk'   same external_id known under another source (step 2)
  - 'rule:<id>'    pattern-rule registry hit (step 3) — the matching rule's id
                   from pattern_rules.yaml, e.g. 'rule:pump_p_tag'
  - 'manual'       human-confirmed (written by review tooling, not here)
  - 'llm_v<n>'     LLM classifier placeholder — not used until Sprint 3
Seed-loaded rows keep mapping_source='authoritative_import' (provenance of the
import); resolving against them still REPORTS 'exact_match'.

Below-threshold persistence (Phase 1 spec §2.5): when a step produces a single
candidate whose confidence is under min_confidence, a pending-review alias is
written (resolution_status='pending_review', resolved_by='system',
candidate_alternatives = every candidate considered) instead of the deprecated
asset_aliases_unresolved flow. With multiple equally-scored crosswalk
candidates there is no defensible primary binding, so the resolution returns
'ambiguous' and falls back to the unresolved queue; a no-candidate miss also
keeps the unresolved queue (see models.AssetAliasUnresolved deprecation note).

Exact-match rows below threshold are demoted to pending_review ONCE (provenance
carried over); already-pending rows are a no-op, and human_validated/'manual'
rows are never demoted. Sources missing from SOURCE_SYSTEM_CATEGORIES also use
the unresolved queue (source_system_type is NOT NULL and is never guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import UUID

from rca_contracts import ResolveStatus

from .config import auto_accept_threshold
from .models import SOURCE_SYSTEM_CATEGORIES
from .pattern_rules import PatternRule, apply_rules, load_rules
from .repository import AliasRow, AssetRepository

_CROSSWALK_CONFIDENCE = 0.85


@dataclass(frozen=True)
class AssetResolution:
    status: ResolveStatus
    asset_id: UUID | None
    confidence: float
    mapping_source: str
    alternatives: list[UUID] = field(default_factory=list)


async def _persist_pending_review(repo: AssetRepository, tenant: UUID, source: str,
                                  external_id: str, asset_id: UUID, confidence: float,
                                  method: str) -> None:
    """Bind a single below-threshold candidate as a pending_review alias (§2.5)."""
    asset = await repo.get_asset(tenant, asset_id)
    if asset is None:  # dangling alias target; fall back to the unresolved queue
        await repo.upsert_unresolved(tenant, source, external_id,
                                     {"reason": "candidate_asset_missing", "method": method})
        return
    category = SOURCE_SYSTEM_CATEGORIES.get(source)
    if category is None:
        # Unknown source system: source_system_type is NOT NULL and we won't guess it,
        # so the candidate goes to the deprecated unresolved queue instead of being
        # persisted as a pending_review alias with a fabricated category.
        await repo.upsert_unresolved(tenant, source, external_id,
                                     {"reason": "unknown_source_system", "method": method,
                                      "candidate": {"canonical_id": asset.canonical_id,
                                                    "confidence": confidence}})
        return
    await repo.upsert_alias(AliasRow(
        asset_id=asset_id, tenant_id=tenant, source_system=source, external_id=external_id,
        valid_from=datetime.now(timezone.utc), valid_to=None,
        mapping_source=method, confidence=confidence, is_primary=False,
        source_system_type=category,
        resolution_status="pending_review", resolved_by="system",
        candidate_alternatives=[{"canonical_id": asset.canonical_id,
                                 "confidence": confidence, "method": method}]))


async def _demote_to_pending_review(repo: AssetRepository, tenant: UUID, source: str,
                                    external_id: str, row: AliasRow, method: str) -> None:
    """Supersede a below-threshold ACTIVE alias into pending_review ONCE, carrying over the
    original provenance (mapping_source/confidence/is_primary/confirmed_by/notes/...)."""
    asset = await repo.get_asset(tenant, row.asset_id)
    if asset is None:  # dangling alias target; fall back to the unresolved queue
        await repo.upsert_unresolved(tenant, source, external_id,
                                     {"reason": "candidate_asset_missing", "method": method})
        return
    await repo.upsert_alias(replace(
        row, valid_from=datetime.now(timezone.utc), valid_to=None,
        resolution_status="pending_review", resolved_by="system",
        candidate_alternatives=[{"canonical_id": asset.canonical_id,
                                 "confidence": row.confidence, "method": method}]))


async def resolve_asset(
    repo: AssetRepository,
    external_id: str,
    source: str,
    tenant: UUID,
    *,
    valid_at: datetime | None = None,
    min_confidence: float | None = None,
    rules: list[PatternRule] | None = None,
) -> AssetResolution:
    """Run the 4-step resolution. rules=None uses the default registry for step 3;
    rules=[] disables step 3 entirely (a tag-rule miss falls through to step 4)."""
    if min_confidence is None:
        min_confidence = auto_accept_threshold()

    # Step 1: exact active-alias match (reported as 'exact_match' regardless of how
    # the matched row was originally created, e.g. 'authoritative_import' seeds).
    row = await repo.find_active_alias(tenant, source, external_id, valid_at=valid_at)
    if row is not None:
        # Human judgment outranks the auto-accept threshold: a row a person validated
        # (resolution_status='human_validated') or created (mapping_source='manual') is
        # treated as resolved and is never superseded/demoted back to pending_review.
        if row.resolution_status == "human_validated" or row.mapping_source == "manual":
            return AssetResolution("resolved", row.asset_id, row.confidence, "exact_match")
        status: ResolveStatus = "resolved" if row.confidence >= min_confidence else "unresolved"
        if status == "unresolved" and row.resolution_status != "pending_review":
            # demote ONCE; an already-pending row is left untouched so repeated
            # resolves of the same below-threshold id are idempotent (no row churn)
            await _demote_to_pending_review(repo, tenant, source, external_id,
                                            row, "exact_match")
        return AssetResolution(status, row.asset_id, row.confidence, "exact_match")

    # Step 2: cross-walk via the same external_id known under other sources
    candidates = await repo.find_crosswalk_candidates(tenant, external_id)
    distinct = {c.asset_id for c in candidates}
    if len(distinct) == 1:
        aid = next(iter(distinct))
        status = "resolved" if _CROSSWALK_CONFIDENCE >= min_confidence else "unresolved"
        if status == "unresolved":
            await _persist_pending_review(repo, tenant, source, external_id,
                                          aid, _CROSSWALK_CONFIDENCE, "cross_walk")
        return AssetResolution(status, aid, _CROSSWALK_CONFIDENCE, "cross_walk")
    if len(distinct) > 1:
        # equally-scored candidates -> no defensible primary binding; queue, don't bind
        await repo.upsert_unresolved(tenant, source, external_id,
                                     {"reason": "ambiguous_crosswalk",
                                      "candidates": sorted(str(a) for a in distinct)})
        return AssetResolution("ambiguous", None, _CROSSWALK_CONFIDENCE, "cross_walk",
                               alternatives=sorted(distinct, key=str))

    # Step 3: deterministic pattern rules (Sprint 2a §1.5) -> match by tag. The candidate
    # tag is the rule pattern's named group 'tag' when defined, else the full matched text;
    # method/mapping_source is the matching rule's id (e.g. 'rule:pump_p_tag').
    match = apply_rules(external_id, "tag", rules=rules if rules is not None else load_rules())
    if match is not None:
        asset = await repo.find_asset_by_tag(tenant, match.matched)
        if asset is not None:
            status = "resolved" if match.confidence >= min_confidence else "unresolved"
            if status == "unresolved":
                await _persist_pending_review(repo, tenant, source, external_id,
                                              asset.asset_id, match.confidence, match.rule_id)
            return AssetResolution(status, asset.asset_id, match.confidence, match.rule_id)

    # Step 4: unresolved — no candidate at all; deprecated queue keeps working
    await repo.upsert_unresolved(tenant, source, external_id, {"reason": "no_match"})
    return AssetResolution("unresolved", None, 0.0, "none")


__all__ = ["AssetResolution", "resolve_asset"]
