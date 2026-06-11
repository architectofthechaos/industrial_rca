---
name: rca_run_five_whys_step
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 1200
variables:
  - initial_problem
  - prior_steps
  - evidence_package
  - reference_time
output_schema:
  type: object
  additionalProperties: false
  required: [why_question, answer, answer_source, grounded, is_root_cause]
  properties:
    why_question: {type: string}
    answer: {type: string}
    answer_source:
      type: string
      enum: [evidence_package, kg, engineer_hitl, agent_inference]
    grounded: {type: boolean}
    needs_human_knowledge: {type: boolean}
    is_root_cause: {type: boolean}
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
Advance the 5 Whys analysis by exactly one step. Reference time: {{ reference_time }}.

Initial problem: {{ initial_problem }}
Steps so far: {{ prior_steps }}
Evidence Package: {{ evidence_package }}

Produce the next "why" question and its best answer. Set ``answer_source`` to where the
answer is grounded. Set ``grounded`` true only if the answer is supported by the Evidence
Package or KG. Set ``needs_human_knowledge`` true when only a human can answer (e.g. "was the
operator trained?"). Set ``is_root_cause`` true when this answer is a verified terminal root
cause. Cite supporting evidence via {section, item_id}.
