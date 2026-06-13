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
  - kg_valid_mechanisms
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
Valid ISO 14224 failure-mode codes in the knowledge graph: {{ kg_valid_codes }}
Valid ISO 14224 failure mechanisms for this equipment class (CAN_EXHIBIT → CAUSED_BY): {{ kg_valid_mechanisms }}

Each hypothesis MUST set ``iso14224_failure_mode`` to a code from the valid-codes list AND
``iso14224_mechanism`` to an id from the valid-mechanisms list — pick the MOST SPECIFIC mechanism
the evidence supports. Use ``failure-mechanism:other`` only if no listed mechanism fits. Cite
supporting Evidence Package items and carry a confidence in [0,1]; the primary hypothesis
confidence must be ≥ every alternative's. Add recommended maintenance actions (with priority)
and any open data requests (data to pull, not actions).
