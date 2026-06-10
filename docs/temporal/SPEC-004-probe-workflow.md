# SPEC-004: Probe Workflow (Temporal)

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0003](../adrs/0003-workflow-engine-temporal.md), [0004](../adrs/0004-agent-framework-langgraph.md)

## Purpose

Defines the Temporal workflow topology for a probe — the parent orchestrator, tier child workflows, activities, signals, and versioning.

## Topology

```
ProbeOrchestrator (workflow)
├── ScopeWorkflow (child)
│   ├── Activity: run_agent_tier("scope", probe_state)
│   ├── Activity (per tool): trs.resolve_tag, assets.classify_iso14224, ...
│   └── Signal: tag_confirmation_response (if needed)
├── EvidenceWorkflow (child)
│   ├── Activity: run_agent_tier("evidence", probe_state)
│   └── Activities (parallel): pi.get_series, maximo.get_workorders, ...
├── ReasonWorkflow (child)
│   ├── Activity: run_agent_tier("reason", probe_state)
│   └── Activities: evidence.score_failure_mode, causemap.* ...
└── GovernWorkflow (child)
    ├── Signal: review_decision (HITL — reliability engineer)
    ├── Activity: cmms.preview_writeback, cmms.commit_writeback
    └── Activity: corpus.index_probe, overlay.commit_update
```

## ProbeOrchestrator workflow

```python
@workflow.defn
class ProbeOrchestrator:
    @workflow.run
    async def run(self, trigger: ProbeTrigger) -> ProbeOutcome:
        probe = await workflow.execute_activity(
            create_probe, trigger,
            start_to_close_timeout=timedelta(seconds=30),
        )

        scope_result = await workflow.execute_child_workflow(
            ScopeWorkflow.run, probe.id,
            id=f"probe-{probe.id}-scope",
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        evidence_result = await workflow.execute_child_workflow(
            EvidenceWorkflow.run, probe.id, scope_result,
            id=f"probe-{probe.id}-evidence",
        )

        reason_result = await workflow.execute_child_workflow(
            ReasonWorkflow.run, probe.id, evidence_result,
            id=f"probe-{probe.id}-reason",
        )

        # If reasoning is inconclusive, loop back to evidence with expanded neighborhood
        attempt = 1
        while reason_result.inconclusive and attempt < 3:
            evidence_result = await workflow.execute_child_workflow(
                EvidenceWorkflow.run, probe.id, scope_result, expand=True,
                id=f"probe-{probe.id}-evidence-{attempt+1}",
            )
            reason_result = await workflow.execute_child_workflow(
                ReasonWorkflow.run, probe.id, evidence_result,
                id=f"probe-{probe.id}-reason-{attempt+1}",
            )
            attempt += 1

        govern_result = await workflow.execute_child_workflow(
            GovernWorkflow.run, probe.id, reason_result,
            id=f"probe-{probe.id}-govern",
        )

        return govern_result.outcome
```

## Signals

| Signal | Source | Workflow that awaits |
|---|---|---|
| `tag_confirmation_response` | Reliability eng UI | ScopeWorkflow |
| `review_decision` | Reliability eng UI | GovernWorkflow |
| `cmms_writeback_authorization` | Reliability eng UI | GovernWorkflow |
| `cancel_probe` | Any user with permission | ProbeOrchestrator (cancellation propagates to children) |

## Activity retry policies

| Activity class | maximum_attempts | initial_interval | backoff |
|---|---|---|---|
| Connector reads (PI, Maximo, etc.) | 5 | 1s | exponential, max 60s |
| TRS reads | 3 | 100ms | exponential, max 5s |
| LLM agent step | 2 | 5s | exponential — non-deterministic, limit retries |
| CMMS write | 1 | n/a | no auto-retry; HITL re-issues if failed |
| Overlay commit | 3 | 1s | exponential |

## Versioning

```python
v = workflow.get_version("probe_orchestrator", default_version=1, max_supported=2)
if v == 1:
    # original behavior
else:
    # new behavior
```

In-flight probes complete on their original version. New probes use the latest.

## Payload size

Temporal default payload limit is 2 MB. Evidence bundles can exceed this. We store full bundles in S3/MinIO and pass `bundle_id: UUID` references through workflow payloads. Activities read bundles from object storage by id.

## Idempotency

- `create_probe` uses `idempotency_key = hash(trigger)` to prevent duplicate probes from retried triggers.
- All mutating activities (CMMS write, overlay commit) carry an idempotency key derived from `(probe_id, step_id)`.

## Observability

- Every activity logs `(probe_id, tier, tool, duration_ms, status)` to structured logs.
- OpenTelemetry traces span the full workflow tree.
- Temporal Web UI gives free replay debugging.

## Cancellation

Cancel propagates from parent → child workflows → in-flight activities. Mutating activities (CMMS write, overlay commit) are *not* cancellable once started; they complete or fail. Compensation logic lives in GovernWorkflow.

## Testing

- `temporalio.testing.WorkflowEnvironment` for unit tests with time-skip.
- Integration: full ProbeOrchestrator against simulator MCP servers in docker-compose.
- Replay tests: record real workflow histories, replay against new code to verify backward compatibility.
