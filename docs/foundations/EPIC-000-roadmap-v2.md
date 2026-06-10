# EPIC-000 (v2): Roadmap — Re-sequenced around Use Case 01

**Supersedes the planning intent of [EPIC-000-roadmap.md](EPIC-000-roadmap.md).** That roadmap was
*connector-first*. The end-to-end use case ([rca_use_case_01.pdf](../../rca_use_case_01.pdf)) makes the
real architecture explicit: the platform is **data-model-first / planner-first**. Connectors are
interchangeable adapters that fill a canonical model; the product the use case demonstrates is the
*investigation loop above the connectors* — **Probe → Contextualize → Draft Plan → Data-Availability
Sweep → Earned Questions → Approval → Evidence Gathering → Handoff → Conclusion → KG learning.**

This v2 keeps every line of built code. It re-characterizes what's done as a **foundation layer** and
inserts the investigation layer the use case actually exercises. Nothing is thrown away; several things
are newly named because they were never specified.

---

## What the use case changed about our understanding

1. **The entry point is a vague chat prompt**, not (only) a structured alarm. *"can you look into
   P-2103A — ops says it sounds rough."* Asset is just a string until resolved.
2. **A Planner LLM** generates a draft investigation plan from prompt + resolved context + ISO 14224
   failure-mode tree. This is the heart of the product and was essentially unspecified.
3. **The data-availability sweep** is the signature idea: *the LLM may only ask the engineer a question
   it has earned by confirming a real data gap across all bound entities.* Question burden is inversely
   proportional to data-layer maturity.
4. **The canonical entity model is 12 entities**; we have 5 in contracts. Probe, Plan, Operator Log,
   Failure Event, Reference Data, Person/Role, Asset Class are missing.
5. **The Evidence Package → RCA Conclusion contract is the actual product boundary** (external analysis
   engine). It is undefined in code and carries 25 open questions (use case §9).
6. **The Knowledge Graph is one graph for its whole life.** "Cold" and "warm" are not two scopes or two
   products — they are the *same* KG when empty (new customer) vs. after months of probes. The
   write-back-on-conclusion path and the prior-history-query-during-planning path **both exist from day
   one**; they simply return little when the graph is sparse and more as it fills. The "flywheel" is the
   emergent result of both paths existing, not a separate deferred feature.
7. **Mid-execution check-ins** (pause only on surprises) and **parent/child probe linking** (an
   inspection result spawns a child probe) are first-class lifecycle behaviors.
8. **The prototype RCA engine is a thin in-house stub** (5 Whys + fishbone over candidate modes) — built,
   not deferred — so the platform is demonstrable end-to-end and the integration contract is exercised.

---

## Layered architecture (the new mental model)

```
┌──────────────────────────────────────────────────────────────────┐
│  L4  INVESTIGATION LOOP  (the product the use case demonstrates)   │
│      Probe · Planner · Availability Sweep · Earned Questions ·     │
│      Evidence Package · Handoff · Conclusion · HITL gates          │
├──────────────────────────────────────────────────────────────────┤
│  L3  KNOWLEDGE & LEARNING                                          │
│      Knowledge Graph (read: prior history → planning;              │
│      write: HistoricalFailureEvent on conclusion) · ISO 14224      │
│      ontology · Reference Data (OREDA priors) · pattern detection  │
├──────────────────────────────────────────────────────────────────┤
│  L2  CANONICAL DATA MODEL  (12 entities, vendor-neutral)           │
│      Asset · AssetClass · Tag/Signal · Binding · WorkOrder ·       │
│      FailureEvent · OperatorLog · Document · ReferenceData ·       │
│      Person/Role · Site · System  +  runtime: Probe                │
├──────────────────────────────────────────────────────────────────┤
│  L1  DATA LAYER  (✅ largely built — the old "Track A core")        │
│      MAR · TRS · connector_sdk · 7 connectors · simulators ·       │
│      parity harness                                                │
└──────────────────────────────────────────────────────────────────┘
```

L1 is done. L2 is half-done (5 of 12 entities). L3 and L4 are mostly unspecified — and they are the
product.

---

## Re-sequenced epics

Status: ✅ done · 🟡 partial · 🆕 new (use-case-driven) · 🔁 recharacterized · ⬜ planned/not started

### Layer 1 — Data layer (foundation) — ✅ DONE, recharacterized

| Epic | Was | Now | Status |
|---|---|---|---|
| EPIC-001 Foundations | Foundations | Foundations (contracts base, infra, migrations) | ✅ |
| EPIC-012 MAR | Core service | L1 identity/hierarchy | ✅ |
| EPIC-003 TRS | Core service | L1 tag resolution | ✅ |
| EPIC-013 Connectors + SDK | Phase 3 | L1 source adapters (7 connectors, parity) | ✅ |
| EPIC-002 Simulators | Track B | L1 test sources | ✅ |

**No new work here** except the source-adapter back-half deferred earlier (MAR/TRS source adapters
S12.5–8, S3.4–6) — still legitimately deferred; sim-backed paths cover the demo.

### Layer 2 — Canonical data model — 🟡 PARTIAL, the first new work

| Epic | Scope | Status |
|---|---|---|
| **EPIC-014 Canonical entity model (NEW)** | Add the missing entities to `contracts` as Pydantic + (where persisted) Postgres/graph models: **Probe**, **OperatorLog**, **FailureEvent**, **ReferenceData**, **Person/Role**, **AssetClass** as a first-class ISO 14224 entity, **Site/System** formalized. Reconcile with the 12-entity table in use-case §2.1. | 🆕 |
| EPIC-004 Templates | Equipment-class templates (centrifugal pump v0.3.1). Still needed — the planner uses template defaults (time windows, expected signals). | ⬜ |

### Layer 3 — Knowledge & learning — 🆕 mostly new

| Epic | Scope | Status |
|---|---|---|
| **EPIC-015 ISO 14224 ontology (NEW)** | The failure-mode/mechanism/cause tree as **loaded, queryable data** (not just enum codes). Loads into planner working memory; filters to candidate modes; supplies the codes (BRD/BWR/WEAR_NORMAL) used in the conclusion contract. Closes gap G-ontology. | 🆕 |
| **EPIC-016 Knowledge Graph (NEW)** | Stand up Neo4j (already in ADR-0011 + intended for docker-compose; **currently absent**). Graph schema for the canonical entities + `HistoricalFailureEvent`. **Two paths, both in scope from day one:** (a) **write** — enrichment on approved conclusion; (b) **read** — prior-history query during planning ("prior bearing failures on this class at this plant"). Closes gap G8. | 🆕 |
| **EPIC-017 Pattern detection (NEW, light)** | Periodic cross-asset queries over `HistoricalFailureEvent` nodes → surface fleet observations to the reliability lead (human-review, not automated action). Emergent from EPIC-016; can be a thin first cut for MVP. | 🆕 |

### Layer 4 — Investigation loop — 🆕 the product

| Epic | Scope | Status |
|---|---|---|
| **EPIC-018 Probe intake & contextualization (NEW)** | Chat intake of a vague prompt → create Probe → run asset resolution (MAR), tag enumeration (TRS), history attach, ontology load. Also the structured-alarm intake path (existing SPEC-012 trigger). Two front doors, one Probe. | 🆕 |
| **EPIC-019 Planner & availability sweep (NEW, HIGHEST VALUE)** | LLM draft-plan generation; the **data-availability sweep** that classifies each step auto / ask-engineer / approve / blocked; the **earned-questions** mechanism + its provenance audit record (`entities_checked`, `escalation_reason`, `connector_gap` → CRG items). This is the signature capability. | 🆕 |
| EPIC-006 Temporal Workflows | 🔁 Recharacterized: the durable spine that runs the 10-stage lifecycle, holds HITL gates, and supports parent/child probe re-entry (Stage 10 loop). | ⬜ |
| EPIC-007 LangGraph Agents | 🔁 Recharacterized: the planner + evidence-gathering executors run here. **Tier-bounded catalogs dropped for Phase 1** (decision 2026-06-09 — all tools exposed). | ⬜ |
| EPIC-005 MCP Servers | 🔁 Reduced: assemble per-connector + service MCP servers; **no tier layer for Phase 1**. | 🟡→reduced |
| **EPIC-020 Evidence Package + Handoff contract (NEW)** | The `EvidencePackage` (platform→engine) and `RCAConclusion` (engine→platform) schemas from use-case §6; schema validation; the **thin in-house RCA stub** (5 Whys + fishbone over candidate modes). Carries the 25 open questions (§9) as a living spec. | 🆕 |
| EPIC-008 HITL UI | 🔁 Recharacterized: the three gates — final-plan approval (Gate 1), mid-execution check-ins (Gate 2, surprise-only), conclusion review/edit/approve (Gate 3). Plan review, earned-question chat, conclusion editor. | ⬜ |
| **EPIC-021 Post-RCA write-back (NEW)** | On approved conclusion: persist `HistoricalFailureEvent` to KG (EPIC-016), create follow-up work order via the bound work-order entity, notify stakeholders, schedule follow-up monitoring. | 🆕 |

### Layer 5 — Quality & pilot — ⬜ unchanged in intent

| Epic | Status |
|---|---|
| EPIC-009 Evaluation Harness — golden probes (the use-case scenario is golden probe #1) | ⬜ |
| EPIC-010 Observability — cost/HITL dashboards | ⬜ |
| EPIC-011 Pilot Readiness | ⬜ |

---

## New critical path (use-case-driven)

```
[L1 done] → EPIC-014 entities → EPIC-015 ontology ─┐
                                                    ├→ EPIC-018 intake → EPIC-019 planner+sweep
            EPIC-016 KG (read+write) ───────────────┘                          │
                                                                               ▼
                          EPIC-006 workflow spine ← EPIC-007 agents ← EPIC-020 evidence+handoff+stub
                                                                               │
                                                          EPIC-008 HITL gates ─┤
                                                          EPIC-021 write-back ─┘
                                                                               │
                                                            EPIC-009 eval (golden probe) → pilot
```

**The single highest-value new epic is EPIC-019 (planner + availability sweep).** It is what makes the
product the product. Everything in L2/L3 exists to feed it; everything in EPIC-020/008/021 exists to act
on its output.

---

## Suggested build order for the next phase

1. **EPIC-014** canonical entities (Probe, OperatorLog, FailureEvent, ReferenceData, Person/Role,
   AssetClass) — unblocks everything in L3/L4; pure contracts work, fast.
2. **EPIC-015** ISO 14224 ontology as loaded data — small, unblocks the planner's mode filtering.
3. **EPIC-016** Knowledge Graph (Neo4j + schema + read/write paths) — can run parallel to 015.
4. **EPIC-018** probe intake & contextualization — wires L1 (MAR/TRS) into a Probe.
5. **EPIC-019** planner + availability sweep — the centerpiece.
6. **EPIC-020** evidence package + handoff contract + thin stub — makes it demonstrable end-to-end.
7. **EPIC-006/007/008/021** workflow, agents, HITL gates, write-back — assemble the loop.

---

## Open items to resolve before/while building

- **§9 has 25 open questions** about the analysis-engine contract. For MVP the thin in-house stub lets us
  *choose* the answers (structured JSON in, ISO 14224 codes out) and refine when a real engine appears.
  Worth a short SPEC capturing the chosen answers as the prototype contract.
- **Vibration realism**: the demo narrative depends on an FFT peak at 158.2 Hz (BPFI). Lessons log already
  flags the sim as trend-only (scalar RMS, no spectra). **Confirm the sim can synthesize the spectral
  feature the use case relies on, or the planner/evidence step must read pre-computed spectral features.**
- **Templates (EPIC-004)** still needed for planner defaults — slot it alongside EPIC-014/015.
- Promote this v2 to replace EPIC-000 once reviewed; update PROGRESS.xlsx tabs to the layered structure.
```
