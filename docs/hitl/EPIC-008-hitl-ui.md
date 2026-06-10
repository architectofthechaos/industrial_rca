# EPIC-008: HITL UI

**Goal**: Minimal reliability-engineer UI to handle the four HITL gates from [SPEC-005](SPEC-005-hitl-gates.md).

**Duration**: Week 7–10

## Stories

### S8.1 — API
- REST endpoints: list pending HITL requests, fetch detail, submit decision.
- Auth: bearer token; role check per gate.
- Dispatches Temporal signal on decision.

**DoD**: API contracts match SPEC-005; signals reach workflows.

### S8.2 — Web UI
- Stack: Next.js + Tailwind (or HTMX if team prefers low-JS).
- Pages: queue, request detail (per gate type), probe inspector.
- Tag confirmation: search + suggest + confirm.
- Cause map review: structured edit of nodes/edges/evidence bindings.
- CMMS preview + authorize.

**DoD**: All four gates fully usable end-to-end.

### S8.3 — Notifications
- In-app realtime (WebSocket).
- Optional email/Slack via configurable channel.

**DoD**: Reviewer receives notification on HITL request.

### S8.4 — Rejection capture
- When a reviewer edits or rejects a cause map, capture diff + rationale for overlay learning.

**DoD**: Captured rejection appears as input to `overlay.propose_update`.
