from datetime import datetime, timezone
from uuid import uuid4

from rca_mar.pattern_rules import PatternRule
from rca_mar.repository import AliasRow, InMemoryRepository
from rca_mar.resolution import resolve_asset
from rca_contracts import AssetDescriptor

TENANT = uuid4()
T2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)

# step-3 fixture: dotted historian path with a named 'tag' group; confidence 0.70
# (below the 0.92 default gate) keeps the demotion/pending-review intents intact
_UNS_RULE = PatternRule(id="rule:uns_dotted_tag",
                        pattern=r"[A-Z]+\.(?P<tag>[A-Z]-\d+[A-Z]?)\.",
                        iso14224_class="pump.centrifugal", confidence=0.70, applies_to="tag")


def _asset(asset_id, tag):
    return AssetDescriptor(
        asset_id=asset_id, canonical_id=f"asset:refinery-gc:unit-101:{tag.lower()}",
        tenant_id=TENANT, plant_id="refinery-gc",
        iso14224_class="pump.centrifugal", iso14224_level=6, tag=tag, service=None,
        criticality="A", manufacturer=None, model=None, serial_number=None,
        commissioned_at=None, decommissioned_at=None, location_description=None, description=None)


def _active_alias(repo, source, external_id):
    for a in repo.aliases:
        if a.source_system == source and a.external_id == external_id and a.valid_to is None:
            return a
    return None


async def _seeded():
    repo = InMemoryRepository()
    pump = uuid4()
    await repo.upsert_asset(_asset(pump, "P-101A"))
    await repo.upsert_alias(AliasRow(pump, TENANT, "maximo", "CRDU-P101A", T2020, None,
                                     "authoritative_import", 1.0, True))
    return repo, pump


async def test_exact_match_resolves_and_reports_exact_match():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", "maximo", TENANT)
    # the matched row was seeded as 'authoritative_import'; the resolve-time METHOD is exact_match
    assert r.status == "resolved" and r.asset_id == pump and r.mapping_source == "exact_match"


async def test_exact_match_below_threshold_marks_pending_review():
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, "sap_pm", "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    assert r.status == "unresolved" and r.mapping_source == "exact_match"
    pending = _active_alias(repo, "sap_pm", "10009999")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.resolved_by == "system"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.6, "method": "exact_match"}]
    assert (TENANT, "sap_pm", "10009999") not in repo.unresolved


async def test_below_threshold_demotion_is_idempotent_no_row_churn():
    # repeated resolves of the same below-threshold id must not write a new row per call:
    # the first resolve demotes once, later resolves see pending_review and no-op
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, "sap_pm", "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r1 = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    rows_after_first = len(repo.aliases)
    r2 = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    r3 = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    assert len(repo.aliases) == rows_after_first
    assert r1.status == "unresolved" and r2 == r1 and r3 == r1 and r1.asset_id == pump
    pending = _active_alias(repo, "sap_pm", "10009999")
    assert pending is not None and pending.resolution_status == "pending_review"


async def test_demoted_alias_carries_over_provenance():
    # demotion supersedes the row but must NOT drop the original provenance fields
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, "sap_pm", "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, True,
                                     source_system_type="cmms", notes="from walkdown"))
    await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    pending = _active_alias(repo, "sap_pm", "10009999")
    assert pending is not None
    assert pending.resolution_status == "pending_review" and pending.resolved_by == "system"
    assert pending.mapping_source == "rule:tag_pattern"   # carried over, not overwritten
    assert pending.confidence == 0.6 and pending.is_primary is True
    assert pending.notes == "from walkdown" and pending.source_system_type == "cmms"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.6, "method": "exact_match"}]


async def test_human_validated_below_threshold_resolves_and_is_untouched():
    # human validation overrides the auto-accept threshold: never demoted, never superseded
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, "sap_pm", "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False,
                                     resolution_status="human_validated", resolved_by="jane",
                                     confirmed_by="jane", notes="confirmed against P&ID"))
    before = list(repo.aliases)
    r = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    assert r.status == "resolved" and r.asset_id == pump and r.confidence == 0.6
    assert r.mapping_source == "exact_match"
    assert repo.aliases == before                          # nothing written or modified


async def test_manual_mapping_below_threshold_resolves_and_is_untouched():
    # mapping_source='manual' rows are human-created: same override as human_validated
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, "sap_pm", "10009999", T2020, None,
                                     "manual", 0.6, False))
    before = list(repo.aliases)
    r = await resolve_asset(repo, "10009999", "sap_pm", TENANT)
    assert r.status == "resolved" and r.asset_id == pump and r.confidence == 0.6
    assert repo.aliases == before


async def test_unknown_source_below_threshold_goes_to_unresolved_queue():
    # an unknown source system has no honest source_system_type (NOT NULL), so the
    # below-threshold candidate must land in the deprecated unresolved queue,
    # never as a pending_review alias with a guessed category
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", "weird_dcs", TENANT)
    assert r.status == "unresolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    assert _active_alias(repo, "weird_dcs", "CRDU-P101A") is None
    assert (TENANT, "weird_dcs", "CRDU-P101A") in repo.unresolved


async def test_crosswalk_below_default_gate_is_pending_review():
    # crosswalk confidence 0.85 < default 0.92 gate -> unresolved + pending_review alias
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", "pi_af", TENANT)
    assert r.status == "unresolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    assert r.confidence == 0.85
    pending = _active_alias(repo, "pi_af", "CRDU-P101A")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.source_system_type == "asset_hierarchy"
    assert pending.candidate_alternatives[0]["method"] == "cross_walk"
    assert (TENANT, "pi_af", "CRDU-P101A") not in repo.unresolved


async def test_crosswalk_single_candidate_resolves_when_gate_lowered():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", "pi_af", TENANT, min_confidence=0.8)
    assert r.status == "resolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    # at-or-above threshold resolves are read-only: no alias is written
    assert _active_alias(repo, "pi_af", "CRDU-P101A") is None


async def test_ambiguous_crosswalk_binds_nothing_and_queues():
    # two distinct assets own the same external_id under different sources -> no defensible
    # primary binding; return ambiguous, queue in the (deprecated) unresolved table
    repo, pump = await _seeded()
    other = uuid4()
    await repo.upsert_asset(_asset(other, "P-103A"))
    await repo.upsert_alias(AliasRow(other, TENANT, "sap_pm", "CRDU-P101A", T2020, None,
                                     "authoritative_import", 1.0, True))
    r = await resolve_asset(repo, "CRDU-P101A", "uns", TENANT)
    assert r.status == "ambiguous" and r.asset_id is None
    assert set(r.alternatives) == {pump, other}
    assert _active_alias(repo, "uns", "CRDU-P101A") is None
    assert (TENANT, "uns", "CRDU-P101A") in repo.unresolved


async def test_rule_match_below_default_gate_is_pending_review():
    # the candidate tag comes from the rule pattern's named 'tag' group; mapping_source
    # and the persisted method are the matching rule's id (Sprint 2a §1.5)
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", "uns", TENANT, rules=[_UNS_RULE])
    assert r.status == "unresolved" and r.mapping_source == "rule:uns_dotted_tag"
    pending = _active_alias(repo, "uns", "SITE.P-101A.PV")
    assert pending is not None and pending.asset_id == pump
    assert pending.resolution_status == "pending_review" and pending.resolved_by == "system"
    assert pending.source_system_type == "historian"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.70, "method": "rule:uns_dotted_tag"}]
    assert (TENANT, "uns", "SITE.P-101A.PV") not in repo.unresolved


async def test_rule_match_passes_when_min_confidence_lowered():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", "uns", TENANT, min_confidence=0.7,
                            rules=[_UNS_RULE])
    assert r.status == "resolved" and r.asset_id == pump
    assert r.mapping_source == "rule:uns_dotted_tag"


async def test_env_threshold_honored(monkeypatch):
    # MAR_AUTO_ACCEPT_THRESHOLD lowers the default gate; the rule (0.70) then auto-accepts
    monkeypatch.setenv("MAR_AUTO_ACCEPT_THRESHOLD", "0.5")
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", "uns", TENANT, rules=[_UNS_RULE])
    assert r.status == "resolved" and r.asset_id == pump


async def test_default_registry_used_when_no_rules_passed():
    # rules=None -> seed_data/pattern_rules.yaml; rule:pump_p_tag has no named 'tag'
    # group, so the candidate tag is the FULL matched text ('P-101A'); confidence 0.85
    # sits below the 0.92 default gate -> pending review under the rule's id
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "P-101A", "uns", TENANT)
    assert r.status == "unresolved" and r.asset_id == pump
    assert r.mapping_source == "rule:pump_p_tag" and r.confidence == 0.85
    pending = _active_alias(repo, "uns", "P-101A")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.mapping_source == "rule:pump_p_tag"


async def test_unknown_is_unresolved_and_queued():
    repo, _pump = await _seeded()
    r = await resolve_asset(repo, "ZZZ-999", "sap_pm", TENANT)
    assert r.status == "unresolved" and r.asset_id is None and r.mapping_source == "none"
    assert (TENANT, "sap_pm", "ZZZ-999") in repo.unresolved


async def test_candidate_asset_missing_lands_in_unresolved_queue():
    # alias whose asset_id points at a non-existent asset -> candidate_asset_missing reason,
    # no pending_review alias written (resolution.py _demote_to_pending_review returns early)
    repo = InMemoryRepository()
    ghost_id = uuid4()
    # NOTE: intentionally NOT upsert_asset(ghost_id) — dangling alias target
    await repo.upsert_alias(AliasRow(ghost_id, TENANT, "sap_pm", "GHOST-001", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r = await resolve_asset(repo, "GHOST-001", "sap_pm", TENANT)
    assert r.status == "unresolved" and r.mapping_source == "exact_match"
    # must land in the unresolved queue with reason=candidate_asset_missing
    key = (TENANT, "sap_pm", "GHOST-001")
    assert key in repo.unresolved
    assert repo.unresolved[key]["candidate_payload"]["reason"] == "candidate_asset_missing"
    # the demotion short-circuits before upsert_alias, so no pending_review alias is written
    active = _active_alias(repo, "sap_pm", "GHOST-001")
    assert active is None or active.resolution_status != "pending_review"
