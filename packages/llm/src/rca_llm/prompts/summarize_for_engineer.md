---
name: summarize_for_engineer
version: v1
model: claude-haiku-4-5-20251001
temperature: 0.0
max_tokens: 600
variables:
  - context
  - open_questions
---
Write a short, plain-language summary for the reliability engineer explaining why the agent
is asking the questions below and what it currently believes.

Working context: {{ context }}
Open questions being asked this turn: {{ open_questions }}

Two or three sentences. No markdown headers. Address the engineer directly.
