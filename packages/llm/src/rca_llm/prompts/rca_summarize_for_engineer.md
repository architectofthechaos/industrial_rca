---
name: rca_summarize_for_engineer
version: v1
model: claude-haiku-4-5-20251001
temperature: 0.0
max_tokens: 800
variables:
  - conclusion
---
Write a concise plain-language briefing for the reliability engineer reviewing this RCA
conclusion. Cover the primary hypothesis, the strongest supporting evidence, and the
recommended actions awaiting approval.

Conclusion: {{ conclusion }}

Four to six sentences. Address the engineer directly. No markdown headers.
