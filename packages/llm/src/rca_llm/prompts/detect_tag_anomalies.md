---
name: detect_tag_anomalies
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 1500
variables:
  - tag_summaries
  - reference_time
output_schema:
  type: object
  additionalProperties: false
  required: [anomalies]
  properties:
    anomalies:
      type: array
      items:
        type: object
        required: [tag_name, summary, severity]
        properties:
          tag_name: {type: string}
          role: {type: string}
          summary: {type: string}
          severity: {type: string, enum: [normal, elevated, critical]}
---
Reference time: {{ reference_time }}. Review these per-tag summary statistics and trends and
flag anomalies relevant to a developing failure:

{{ tag_summaries }}

For each tag that looks abnormal, return its name, a one-line summary of the anomaly, and a
severity (normal / elevated / critical). Omit tags that look healthy.
