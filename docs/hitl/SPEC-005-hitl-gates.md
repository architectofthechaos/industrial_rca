# SPEC-005: Human-in-the-Loop (HITL) Gates

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0003](../adrs/0003-workflow-engine-temporal.md)

## Purpose

Defines the standard pattern for human-in-the-loop pauses in a probe — what triggers them, how the workflow waits, what the payload looks like, and how the response is recorded.

## HITL gate types

| Gate | Trigger | Required role | Decision shape |
|---|---|---|---|
| `tag_confirmation_needed` | TRS returns unresolved or low-confidence | Plant engineer | Map raw tag → signal_id (or skip) |
| `cause_map_review` | Reason tier completes | Reliability engineer | Approve / edit / reject |
| `cmms_writeback_authorization` | Cause map approved | Reliability engineer + plant approver | Authorize / decline write-back |
| `structural_overlay_change` | Overlay proposes structural change | Template owner | Approve / reject / modify |

## Pattern

Each HITL gate is a Temporal signal awaited by a workflow:

```python
@workflow.defn
class GovernWorkflow:
    def __init__(self):
        self.review: ReviewDecision | None = None

    @workflow.signal
    def submit_review(self, decision: ReviewDecision) -> None:
        self.review = decision

    @workflow.run
    async def run(self, probe_id: UUID, reason_result: ReasonResult) -> GovernResult:
        await workflow.execute_activity(
            emit_hitl_request,
            HITLRequest(gate="cause_map_review", probe_id=probe_id, payload=reason_result),
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.wait_condition(lambda: self.review is not None, timeout=timedelta(days=7))
        if self.review is None:
            # timeout — escalate
            return GovernResult(status="escalated_timeout")
        # ... proceed based on self.review
```

## HITLRequest payload

```python
class HITLRequest(BaseModel):
    request_id: UUID
    probe_id: UUID
    gate: Literal[
        "tag_confirmation_needed",
        "cause_map_review",
        "cmms_writeback_authorization",
        "structural_overlay_change",
    ]
    required_role: str
    title: str
    description: str
    payload: dict           # gate-specific structured data
    deadline: AwareDatetime | None
    created_at: AwareDatetime
```

## Decision payload

```python
class HITLDecision(BaseModel):
    request_id: UUID
    gate: str
    decided_at: AwareDatetime
    decided_by: str           # user id
    decision: Literal["approve", "edit", "reject", "skip", "escalate"]
    edits: dict | None = None     # structured edits if decision == 'edit'
    rationale: str | None = None
```

Decisions are persisted to the audit log keyed by `request_id`, and dispatched as a Temporal signal to the awaiting workflow.

## Timeout policy

- Default timeout: 7 days for review gates, 24 hours for tag confirmation.
- Timeout behavior: workflow transitions to `escalated_timeout` state. Probe is held; an escalation notification is emitted.
- Timeouts are configurable per gate per tenant.

## UI integration

- HITL requests appear in a queue in the reliability engineer UI.
- Engineer's response calls `POST /probes/{probe_id}/hitl/{request_id}/decision`.
- The API handler converts the decision to a `HITLDecision` and signals the workflow via Temporal client.

## Rejection capture (for learning)

When a reviewer rejects or edits a cause map, the system captures:
- What the agent proposed
- What the human changed (diff)
- Free-text rationale
- Any new evidence the human attached

This becomes input to overlay learning ([SPEC-010 Overlay Learning](SPEC-010-overlay-learning.md)).

## Permissions

- HITL gates have a `required_role` field.
- The API enforces role-based access before accepting decisions.
- The audit log records `decided_by` for every decision.

## Notifications

- HITL request emits in-app notification + (optionally) email/Slack/Teams to users in `required_role`.
- Reminders at 50% and 90% of timeout.
- Escalation at timeout to a configured escalation group.

## Idempotency

- A submitted decision for an already-decided request is a 409 Conflict.
- Workflow signals are deduplicated by `request_id`.
