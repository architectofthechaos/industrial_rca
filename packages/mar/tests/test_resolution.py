from datetime import datetime, timezone
from uuid import uuid4

from rca_mar.pattern_rules import PatternRule
from rca_mar.repository import AliasRow, ConnectionRow, InMemoryRepository
from rca_mar.resolution import resolve_asset
from rca_contracts import AssetDescriptor

TENANT = uuid4()
T2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)

# Synth default connection ids (Sprint 2b §1.2), one per legacy source the tests exercise.
CONN_MAXIMO = "refinery-gc.cmms.maximo-default"
CONN_SAP = "refinery-gc.cmms.sap-pm-default"
CONN_PI_AF = "refinery-gc.hierarchy.pi-af-default"
CONN_UNS = "refinery-gc.historian.uns-default"

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


def _conn(connection_id, category, status, connector_type) -> ConnectionRow:
    return ConnectionRow(
        connection_id=connection_id, plant_id="refinery-gc", category=category,
        connector_type=connector_type, display_name=f"{connector_type} (default)",
        base_url="http://localhost:9000", auth_config={"type": "none", "secret_ref": None},
        status=status)


def _active_alias(repo, connection_id, external_id):
    for a in repo.aliases:
        if a.connection_id == connection_id and a.external_id == external_id and a.valid_to is None:
            return a
    return None


async def _seeded():
    repo = InMemoryRepository()
    pump = uuid4()
    await repo.upsert_asset(_asset(pump, "P-101A"))
    # connections the resolution write-paths need (sap_pm parked disabled to avoid the
    # active-cmms clash with maximo, but it still exists so pending_review can FK it).
    await repo.upsert_connection(_conn(CONN_MAXIMO, "cmms", "active", "maximo"))
    await repo.upsert_connection(_conn(CONN_SAP, "cmms", "disabled", "sap_pm"))
    await repo.upsert_connection(_conn(CONN_PI_AF, "hierarchy", "active", "pi_af"))
    await repo.upsert_connection(_conn(CONN_UNS, "historian", "active", "uns"))
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_MAXIMO, "CRDU-P101A", T2020, None,
                                     "authoritative_import", 1.0, True))
    return repo, pump


async def test_exact_match_resolves_and_reports_exact_match():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", CONN_MAXIMO, TENANT)
    # the matched row was seeded as 'authoritative_import'; the resolve-time METHOD is exact_match
    assert r.status == "resolved" and r.asset_id == pump and r.mapping_source == "exact_match"


async def test_exact_match_below_threshold_marks_pending_review():
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_SAP, "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    assert r.status == "unresolved" and r.mapping_source == "exact_match"
    pending = _active_alias(repo, CONN_SAP, "10009999")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.resolved_by == "system"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.6, "method": "exact_match"}]
    assert (TENANT, CONN_SAP, "10009999") not in repo.unresolved


async def test_below_threshold_demotion_is_idempotent_no_row_churn():
    # repeated resolves of the same below-threshold id must not write a new row per call:
    # the first resolve demotes once, later resolves see pending_review and no-op
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_SAP, "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r1 = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    rows_after_first = len(repo.aliases)
    r2 = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    r3 = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    assert len(repo.aliases) == rows_after_first
    assert r1.status == "unresolved" and r2 == r1 and r3 == r1 and r1.asset_id == pump
    pending = _active_alias(repo, CONN_SAP, "10009999")
    assert pending is not None and pending.resolution_status == "pending_review"


async def test_demoted_alias_carries_over_provenance():
    # demotion supersedes the row but must NOT drop the original provenance fields
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_SAP, "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, True,
                                     notes="from walkdown"))
    await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    pending = _active_alias(repo, CONN_SAP, "10009999")
    assert pending is not None
    assert pending.resolution_status == "pending_review" and pending.resolved_by == "system"
    assert pending.mapping_source == "rule:tag_pattern"   # carried over, not overwritten
    assert pending.confidence == 0.6 and pending.is_primary is True
    assert pending.notes == "from walkdown"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.6, "method": "exact_match"}]


async def test_human_validated_below_threshold_resolves_and_is_untouched():
    # human validation overrides the auto-accept threshold: never demoted, never superseded
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_SAP, "10009999", T2020, None,
                                     "rule:tag_pattern", 0.6, False,
                                     resolution_status="human_validated", resolved_by="jane",
                                     confirmed_by="jane", notes="confirmed against P&ID"))
    before = list(repo.aliases)
    r = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    assert r.status == "resolved" and r.asset_id == pump and r.confidence == 0.6
    assert r.mapping_source == "exact_match"
    assert repo.aliases == before                          # nothing written or modified


async def test_manual_mapping_below_threshold_resolves_and_is_untouched():
    # mapping_source='manual' rows are human-created: same override as human_validated
    repo, pump = await _seeded()
    await repo.upsert_alias(AliasRow(pump, TENANT, CONN_SAP, "10009999", T2020, None,
                                     "manual", 0.6, False))
    before = list(repo.aliases)
    r = await resolve_asset(repo, "10009999", CONN_SAP, TENANT)
    assert r.status == "resolved" and r.asset_id == pump and r.confidence == 0.6
    assert repo.aliases == before


async def test_unknown_connection_below_threshold_goes_to_unresolved_queue():
    # an alias FKs its connection: a below-threshold candidate keyed by a connection_id with
    # no matching `connections` row must land in the deprecated unresolved queue (reason
    # 'unknown_connection'), never as a pending_review alias for a nonexistent connection
    repo, pump = await _seeded()
    unknown = "refinery-gc.historian.ghost-default"
    r = await resolve_asset(repo, "CRDU-P101A", unknown, TENANT)
    assert r.status == "unresolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    assert _active_alias(repo, unknown, "CRDU-P101A") is None
    assert (TENANT, unknown, "CRDU-P101A") in repo.unresolved
    assert repo.unresolved[(TENANT, unknown, "CRDU-P101A")][
        "candidate_payload"]["reason"] == "unknown_connection"


async def test_crosswalk_below_default_gate_is_pending_review():
    # crosswalk confidence 0.85 < default 0.92 gate -> unresolved + pending_review alias
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", CONN_PI_AF, TENANT)
    assert r.status == "unresolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    assert r.confidence == 0.85
    pending = _active_alias(repo, CONN_PI_AF, "CRDU-P101A")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.candidate_alternatives[0]["method"] == "cross_walk"
    assert (TENANT, CONN_PI_AF, "CRDU-P101A") not in repo.unresolved


async def test_crosswalk_single_candidate_resolves_when_gate_lowered():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "CRDU-P101A", CONN_PI_AF, TENANT, min_confidence=0.8)
    assert r.status == "resolved" and r.asset_id == pump and r.mapping_source == "cross_walk"
    # at-or-above threshold resolves are read-only: no alias is written
    assert _active_alias(repo, CONN_PI_AF, "CRDU-P101A") is None


async def test_ambiguous_crosswalk_binds_nothing_and_queues():
    # two distinct assets own the same external_id under different sources -> no defensible
    # primary binding; return ambiguous, queue in the (deprecated) unresolved table
    repo, pump = await _seeded()
    other = uuid4()
    await repo.upsert_asset(_asset(other, "P-103A"))
    await repo.upsert_alias(AliasRow(other, TENANT, CONN_SAP, "CRDU-P101A", T2020, None,
                                     "authoritative_import", 1.0, True))
    r = await resolve_asset(repo, "CRDU-P101A", CONN_UNS, TENANT)
    assert r.status == "ambiguous" and r.asset_id is None
    assert set(r.alternatives) == {pump, other}
    assert _active_alias(repo, CONN_UNS, "CRDU-P101A") is None
    assert (TENANT, CONN_UNS, "CRDU-P101A") in repo.unresolved


async def test_rule_match_below_default_gate_is_pending_review():
    # the candidate tag comes from the rule pattern's named 'tag' group; mapping_source
    # and the persisted method are the matching rule's id (Sprint 2a §1.5)
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", CONN_UNS, TENANT, rules=[_UNS_RULE])
    assert r.status == "unresolved" and r.mapping_source == "rule:uns_dotted_tag"
    pending = _active_alias(repo, CONN_UNS, "SITE.P-101A.PV")
    assert pending is not None and pending.asset_id == pump
    assert pending.resolution_status == "pending_review" and pending.resolved_by == "system"
    assert pending.candidate_alternatives == [
        {"canonical_id": "asset:refinery-gc:unit-101:p-101a",
         "confidence": 0.70, "method": "rule:uns_dotted_tag"}]
    assert (TENANT, CONN_UNS, "SITE.P-101A.PV") not in repo.unresolved


async def test_rule_match_passes_when_min_confidence_lowered():
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", CONN_UNS, TENANT, min_confidence=0.7,
                            rules=[_UNS_RULE])
    assert r.status == "resolved" and r.asset_id == pump
    assert r.mapping_source == "rule:uns_dotted_tag"


async def test_env_threshold_honored(monkeypatch):
    # MAR_AUTO_ACCEPT_THRESHOLD lowers the default gate; the rule (0.70) then auto-accepts
    monkeypatch.setenv("MAR_AUTO_ACCEPT_THRESHOLD", "0.5")
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "SITE.P-101A.PV", CONN_UNS, TENANT, rules=[_UNS_RULE])
    assert r.status == "resolved" and r.asset_id == pump


async def test_default_registry_used_when_no_rules_passed():
    # rules=None -> seed_data/pattern_rules.yaml; rule:pump_p_tag has no named 'tag'
    # group, so the candidate tag is the FULL matched text ('P-101A'); confidence 0.85
    # sits below the 0.92 default gate -> pending review under the rule's id
    repo, pump = await _seeded()
    r = await resolve_asset(repo, "P-101A", CONN_UNS, TENANT)
    assert r.status == "unresolved" and r.asset_id == pump
    assert r.mapping_source == "rule:pump_p_tag" and r.confidence == 0.85
    pending = _active_alias(repo, CONN_UNS, "P-101A")
    assert pending is not None and pending.resolution_status == "pending_review"
    assert pending.mapping_source == "rule:pump_p_tag"


async def test_empty_rules_list_disables_step3_entirely():
    # rules=[] (unlike rules=None, which loads the default registry) turns step 3 off:
    # a tag the shipped registry WOULD match falls through to step 4 unresolved
    repo, _pump = await _seeded()
    r = await resolve_asset(repo, "P-101A", CONN_UNS, TENANT, rules=[])
    assert r.status == "unresolved" and r.asset_id is None and r.mapping_source == "none"
    assert (TENANT, CONN_UNS, "P-101A") in repo.unresolved


async def test_unknown_is_unresolved_and_queued():
    repo, _pump = await _seeded()
    r = await resolve_asset(repo, "ZZZ-999", CONN_SAP, TENANT)
    assert r.status == "unresolved" and r.asset_id is None and r.mapping_source == "none"
    assert (TENANT, CONN_SAP, "ZZZ-999") in repo.unresolved


async def test_candidate_asset_missing_lands_in_unresolved_queue():
    # alias whose asset_id points at a non-existent asset -> candidate_asset_missing reason,
    # no pending_review alias written (resolution.py _demote_to_pending_review returns early)
    repo = InMemoryRepository()
    ghost_id = uuid4()
    # NOTE: intentionally NOT upsert_asset(ghost_id) — dangling alias target
    await repo.upsert_alias(AliasRow(ghost_id, TENANT, CONN_SAP, "GHOST-001", T2020, None,
                                     "rule:tag_pattern", 0.6, False))
    r = await resolve_asset(repo, "GHOST-001", CONN_SAP, TENANT)
    assert r.status == "unresolved" and r.mapping_source == "exact_match"
    # must land in the unresolved queue with reason=candidate_asset_missing
    key = (TENANT, CONN_SAP, "GHOST-001")
    assert key in repo.unresolved
    assert repo.unresolved[key]["candidate_payload"]["reason"] == "candidate_asset_missing"
    # the demotion short-circuits before upsert_alias, so no pending_review alias is written
    active = _active_alias(repo, CONN_SAP, "GHOST-001")
    assert active is None or active.resolution_status != "pending_review"
