# SPEC-013: Tenant Onboarding

- **Status**: Draft
- **Owner**: gvishnu
- **Related ADRs**: [0001](../adrs/0001-tag-resolution-service.md), [0011](../adrs/0011-master-asset-registry.md), [0012](../adrs/0012-connectors-own-the-contract.md)
- **Closes gap**: G4 (tenant onboarding workflow undefined)

## Purpose

Define the deterministic, gated workflow that brings a new customer (tenant) from "signed contract" to "first probe runnable." Onboarding is a multi-day human-in-the-loop process; this spec turns it into a Temporal workflow with explicit gates so we never end up with half-onboarded tenants in production.

## Onboarding stages

```
0. Tenant Created
   ↓
1. Connectors Configured        (credentials, endpoints — connector-by-connector)
   ↓
2. Master Asset Registry seeded (MAR populated from source systems)
   ↓
3. TRS Ingestion Complete       (all signals resolved or queued for HITL)
   ↓
4. Equipment Templates Bound    (each asset class pinned to a template version)
   ↓
5. Scenario Smoke Test          (run 1 canned probe end-to-end on a real asset)
   ↓
6. Production Cutover           (alarms/triggers enabled)
```

Each stage has a Temporal child workflow, a gate, and an idempotent re-run path.

## Pydantic contract

```python
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field
from uuid import UUID

OnboardingStage = Literal[
    "tenant_created",
    "connectors_configured",
    "mar_seeded",
    "trs_ingested",
    "templates_bound",
    "smoke_tested",
    "production_cutover",
]

class TenantOnboardingState(BaseModel):
    tenant_id: UUID
    tenant_name: str
    created_at: datetime
    current_stage: OnboardingStage
    stage_started_at: datetime
    stage_completed_at: Optional[datetime] = None

    # Per-stage artifacts
    configured_connectors: list[str] = Field(default_factory=list)  # ["pi","maximo",...]
    mar_asset_count: int = 0
    trs_resolved_count: int = 0
    trs_unresolved_count: int = 0
    bound_templates: dict[str, str] = Field(default_factory=dict)   # {"centrifugal_pump": "v0.3.1"}
    smoke_test_probe_id: Optional[UUID] = None
    smoke_test_passed: Optional[bool] = None

    # Gates
    gates_passed: list[OnboardingStage] = Field(default_factory=list)
    approver: Optional[str] = None  # last human who signed off a gate
```

## Stage details

### Stage 1 — Connectors Configured

For each MVP connector the tenant has:

1. Customer provides endpoint URL + credentials via secure form.
2. Credentials stored in vault, referenced by a `connector_config_id`.
3. **Health check probe**: connector hits a no-op endpoint on the source (e.g., PI Web API `/system`, Maximo `/whoami`).
4. **Latency probe**: 10 sequential reads to characterize p50/p99.
5. Gate: customer engineer signs off "yes that's our PI server, yes the test reads look right."

Failure mode: bad credentials or unreachable endpoint → block, escalate to onboarding engineer.

### Stage 2 — MAR Seeded

1. For each configured connector, run **asset discovery** (see [SPEC-011](SPEC-011-master-asset-registry.md)):
   - PI AF: walk hierarchy, create one AssetDescriptor per element.
   - Maximo: query functional locations.
   - SAP PM: query equipment master.
2. Merge into MAR using cross-source identifiers (PI AF path, Maximo location code, SAP equipment number).
3. Output a **MAR diff report**: how many assets per class, ambiguous merges, orphans.
4. Gate: customer signs off on the diff report.

KPI: ≥ 95% of customer's asset list mapped to MAR entries.

### Stage 3 — TRS Ingestion

1. For each historian/UNS source, run **tag discovery**:
   - PI: enumerate PI Points + AF attribute templates.
   - UNS: collect BIRTH certificates from MQTT.
   - OPC UA: walk address space.
2. For each tag, run alias resolution (see [SPEC-003](SPEC-003-tag-resolution-service.md)) against the MAR.
3. Outputs:
   - `resolved_signals` — confidence ≥ 0.9
   - `unresolved_signals` — needs HITL
4. Gate: ≥ 90% resolved, OR explicit "ship it" from customer with unresolved-tag dashboard URL.

### Stage 4 — Equipment Templates Bound

1. For each asset class present in MAR, the tenant must pick a template version.
2. Default: latest stable template for each class (e.g., `centrifugal_pump@v0.3.1`).
3. Tenant can override per-asset (e.g., one critical pump pinned to v0.2 for stability).
4. Gate: reliability lead signs off.

### Stage 5 — Scenario Smoke Test

1. Onboarding engineer picks a real asset that has had a known historical failure.
2. Runs an operator-source probe with a backdated `detected_at` against that asset.
3. Probe must:
   - Complete tier-1 (scope) without errors.
   - Pull real evidence from at least 3 of the configured connectors.
   - Reach an HITL gate (we don't require a correct RCA — we require the *pipeline* works).
4. Gate: smoke test green.

### Stage 6 — Production Cutover

1. Enable alarm-source and threshold-source triggers (these were disabled until now).
2. Schedule recurring "bad-actor scan" cron.
3. Notify customer via email + UI banner.
4. Onboarding workflow completes.

## Temporal workflow

```python
@workflow.defn
class TenantOnboardingWorkflow:
    @workflow.run
    async def run(self, tenant_id: UUID) -> TenantOnboardingState:
        state = await workflow.execute_activity(create_tenant, tenant_id, ...)

        state = await self._stage_connectors(state)
        await workflow.wait_condition(lambda: state.gates_passed[-1] == "connectors_configured")

        state = await self._stage_mar(state)
        await workflow.wait_condition(lambda: state.gates_passed[-1] == "mar_seeded")

        # ... repeat for each stage ...

        return state
```

Each `_stage_*` is a child workflow that can be cancelled and re-run without polluting state. Gates use Temporal **signals** sent from the onboarding UI when a human clicks "approve."

## Storage

```sql
CREATE TABLE tenant_onboarding (
    tenant_id           UUID PRIMARY KEY REFERENCES tenants(id),
    state               JSONB NOT NULL,        -- full TenantOnboardingState
    current_stage       TEXT NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ
);

CREATE TABLE tenant_onboarding_events (
    event_id            UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES tenants(id),
    stage               TEXT NOT NULL,
    event_type          TEXT NOT NULL,  -- "stage_started", "stage_completed", "gate_approved", "gate_rejected"
    actor               TEXT NOT NULL,
    details             JSONB NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## MCP tools (internal — onboarding UI)

| Tool | Purpose |
|---|---|
| `onboarding.start` | Create a tenant and start the workflow. |
| `onboarding.get_state` | Current state for the onboarding UI. |
| `onboarding.approve_gate` | Sign off a stage gate. |
| `onboarding.reject_gate` | Reject and add notes; rewinds to last passable point. |
| `onboarding.run_smoke_test` | Trigger the scenario smoke test (stage 5). |

## Failure & rollback

- A tenant stuck in any stage > 14 days fires an alert.
- Rejection at any gate writes a row to `tenant_onboarding_events` with reason; workflow stays at that stage.
- Connector reconfiguration mid-onboarding cascades a re-run of MAR + TRS for that source.

## Test plan

1. End-to-end happy path on simulator tenant — must complete all 6 stages in < 30 min wall-clock.
2. Gate rejection at stage 3 — workflow stays paused, state reflects rejection, re-approval resumes.
3. Connector swap mid-onboarding — re-runs MAR diff for affected source only.
4. Concurrent onboardings of 3 tenants — Temporal handles, no cross-tenant data leakage.

## Out of scope (post-MVP)

- Self-service onboarding (we hand-hold all MVP customers)
- Automated connector discovery (customer provides endpoints)
- Migration from a prior RCA system (one-way import only post-MVP)
