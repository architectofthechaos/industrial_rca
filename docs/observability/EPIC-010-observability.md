# EPIC-010: Observability

**Goal**: Every probe is debuggable from the outside.

**Duration**: Week 9–11 (overlaps build)

## Stories

### S10.1 — Structured logging
- JSON logs with `tenant_id`, `probe_id`, `tier`, `tool`, `response_id` on every line.
- Centralized in Loki or equivalent.

**DoD**: Filtering by probe_id surfaces full lifecycle.

### S10.2 — Traces
- OpenTelemetry spans across Temporal workflow → activity → tool call → LLM call.
- Jaeger or Tempo backend.

**DoD**: Full trace tree for a probe is viewable.

### S10.3 — Metrics
- Prometheus metrics: probe duration p50/p95/p99, tool call latency, error rates by code, cost per probe.
- Grafana dashboards.

**DoD**: Dashboard shows real-time activity.

### S10.4 — Cost reporting
- Per-probe cost (LLM tokens + connector API).
- Per-tenant rollup.

**DoD**: Cost report API returns last-30d summary per tenant.

### S10.5 — Probe inspector page
- UI deep-link from logs/traces to the probe inspector.
- Shows timeline, evidence bundle summary, cause map, HITL history, audit trail.

**DoD**: Postmortem of a probe completable without DB access.
