// 0006 — seed the generic "Other" failure mechanism (Sprint 5 G26).
// ISO 14224 B.4 includes an "Other" mechanism category; it is the deterministic fallback when
// the RCA agent's chosen iso14224_mechanism can't be resolved to a specific ontology node
// (the rank-hypotheses prompt is given valid failure-MODE codes but not the mechanism vocabulary,
// so the live LLM occasionally emits an out-of-ontology mechanism). Coercing to this seeded node
// keeps persist_failure_event's "MATCH, never MERGE-create the ontology" invariant (G23) intact.
MERGE (n:FailureMechanism {id: "failure-mechanism:other"})
  SET n.name = "Other",
      n.description = "Other/unspecified failure mechanism (ISO 14224 B.4 'Other'); generic fallback when a mechanism cannot be resolved to a specific ontology node.",
      n.iso14224_ref = "B.4";
