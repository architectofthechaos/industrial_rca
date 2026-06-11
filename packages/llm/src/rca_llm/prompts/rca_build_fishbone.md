---
name: rca_build_fishbone
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 3000
variables:
  - evidence_package
  - kg_ontology
output_schema:
  type: object
  additionalProperties: false
  required: [fishbone]
  properties:
    fishbone:
      type: array
      items:
        type: object
        required: [category, causes]
        properties:
          category:
            type: string
            enum: [Manpower, Method, Machine, Material, Measurement, Environment]
          causes:
            type: array
            items:
              type: object
              required: [cause]
              properties:
                cause: {type: string}
                sub_causes: {type: array, items: {type: string}}
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
Build a 6-category Ishikawa (fishbone) diagram for this failure. Ground every cause in a
specific Evidence Package item; cite it via {section, item_id}.

Evidence Package: {{ evidence_package }}
ISO 14224 ontology context: {{ kg_ontology }}

Populate the categories that the evidence supports (Manpower, Method, Machine, Material,
Measurement, Environment). Do not fabricate causes the evidence cannot support.
