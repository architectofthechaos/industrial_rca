---
name: draft_evidence_plan
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 2500
variables:
  - asset
  - shortlist
  - available_connections
  - kg_context
  - reference_time
output_schema:
  type: object
  additionalProperties: false
  required: [steps]
  properties:
    steps:
      type: array
      items:
        type: object
        required: [step_type, description, parameters, rationale]
        properties:
          step_type:
            type: string
            enum: [tag_history, work_orders, documents, operator_logs, kg_query]
          description: {type: string}
          parameters: {type: object}
          rationale: {type: string}
          estimated_cost: {type: string}
---
Draft an opinionated (not exhaustive) evidence-gathering plan for this investigation.
Reference time: {{ reference_time }}.

Asset: {{ asset }}
Candidate failure modes (ranked): {{ shortlist }}
Connections available for this plant: {{ available_connections }}
Knowledge-graph context: {{ kg_context }}

Produce a small set of concrete steps. Each step's ``step_type`` must be one of
tag_history, work_orders, documents, operator_logs, kg_query. Put step-specific arguments
(tag roles, lookback window, search terms) in ``parameters`` and explain why each step
matters in ``rationale``. Prefer the few steps that most discriminate between the candidate
failure modes.
