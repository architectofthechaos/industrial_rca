---
name: build_failure_mode_shortlist
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 1500
variables:
  - symptoms
  - asset_class
  - kg_failure_modes
  - prior_events
output_schema:
  type: object
  additionalProperties: false
  required: [candidates]
  properties:
    candidates:
      type: array
      items:
        type: object
        required: [iso14224_code, name, rank, confidence, reasoning]
        properties:
          iso14224_code: {type: string}
          name: {type: string}
          rank: {type: integer}
          confidence: {type: number}
          reasoning: {type: string}
---
Rank the candidate ISO 14224 failure modes for this asset, most likely first.

Symptoms reported: {{ symptoms }}
Equipment class: {{ asset_class }}
Failure modes this class can exhibit (from the knowledge graph): {{ kg_failure_modes }}
Prior failure events on this asset / class (empty on a cold knowledge graph): {{ prior_events }}

Only use iso14224_code values that appear in the knowledge-graph failure-mode set. Give each
a confidence in [0,1] and a one-sentence rationale grounded in the symptoms or prior events.
