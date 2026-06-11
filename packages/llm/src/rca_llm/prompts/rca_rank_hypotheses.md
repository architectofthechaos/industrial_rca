---
name: rca_rank_hypotheses
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 3000
variables:
  - evidence_package
  - fishbone
  - five_whys
  - kg_valid_codes
output_schema:
  type: object
  additionalProperties: false
  required: [primary_hypothesis, alternative_hypotheses, recommended_actions]
  properties:
    primary_hypothesis: {$ref: "#/$defs/hypothesis"}
    alternative_hypotheses:
      type: array
      items: {$ref: "#/$defs/hypothesis"}
    recommended_actions:
      type: array
      items:
        type: object
        required: [action, rationale, priority]
        properties:
          action: {type: string}
          rationale: {type: string}
          priority: {type: string, enum: [immediate, next_shutdown, monitor]}
          target: {type: string}
          preconditions: {type: array, items: {type: string}}
    open_data_requests:
      type: array
      items:
        type: object
        required: [request, rationale]
        properties:
          request: {type: string}
          rationale: {type: string}
          target: {type: string}
  $defs:
    hypothesis:
      type: object
      required: [iso14224_failure_mode, iso14224_mechanism, confidence, narrative]
      properties:
        iso14224_failure_mode: {type: string}
        iso14224_mechanism: {type: string}
        iso14224_cause: {type: string}
        confidence: {type: number}
        narrative: {type: string}
        supporting_evidence:
          type: array
          items:
            type: object
            required: [section, item_id]
            properties:
              section: {type: string}
              item_id: {type: string}
              relevance: {type: string}
---
Rank the failure hypotheses: one primary plus up to two alternatives.

Evidence Package: {{ evidence_package }}
Fishbone: {{ fishbone }}
5 Whys chain: {{ five_whys }}
Valid ISO 14224 codes in the knowledge graph (failure modes + mechanisms): {{ kg_valid_codes }}

Each hypothesis MUST use an ``iso14224_failure_mode`` and ``iso14224_mechanism`` drawn from
the provided valid-codes list, cite supporting Evidence Package items, and carry a confidence
in [0,1]. The primary hypothesis confidence must be ≥ every alternative's. Add recommended
maintenance actions (with priority) and any open data requests (data to pull, not actions).
