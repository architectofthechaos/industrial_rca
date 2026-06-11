---
name: rca_detect_evidence_gaps
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 1200
variables:
  - fishbone
  - evidence_package
  - kg_warm
output_schema:
  type: object
  additionalProperties: false
  required: [needs_hitl, questions]
  properties:
    needs_hitl: {type: boolean}
    questions:
      type: array
      items:
        type: object
        required: [text, question_type]
        properties:
          text: {type: string}
          question_type:
            type: string
            enum: [clarification, context, scope, approval]
---
Decide whether the engineer should fill any evidence gaps BEFORE the 5 Whys begins.

Fishbone produced: {{ fishbone }}
Evidence Package: {{ evidence_package }}
Knowledge graph is warm (has prior events): {{ kg_warm }}

If the fishbone exposes gaps only a human can fill (e.g. missing maintenance history, unknown
process-upset window), set needs_hitl true and batch the questions. On a cold knowledge graph,
ask more context questions up front. If the evidence is sufficient, set needs_hitl false and
return an empty questions list.
