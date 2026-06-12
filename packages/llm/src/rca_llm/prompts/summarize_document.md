---
name: summarize_document
version: v1
model: claude-haiku-4-5-20251001
temperature: 0.0
max_tokens: 120
variables:
  - document_text
---
Summarise the following source document in one or two factual sentences for use as a retrieval
description. State what the document is and the key facts it records. No preamble, no markdown.

Document:
{{ document_text }}
