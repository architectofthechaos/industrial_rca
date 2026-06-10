# EPIC-011: Pilot Readiness

**Goal**: Ready to connect to one real customer environment.

**Duration**: Week 11–12

## Stories

### S11.1 — Auth and multi-tenancy hardening
- Tenant isolation enforced at every API + DB query.
- SSO support (OIDC / SAML).
- Service accounts and credential broker pattern for connector credentials.

**DoD**: Two-tenant smoke test confirms isolation.

### S11.2 — Deployment artifacts
- Helm chart or docker-compose-prod with secrets management.
- Database backups, retention policies.
- Disaster recovery runbook.

**DoD**: Cold-start deploy to a fresh environment in < 1 hour.

### S11.3 — Real connector parity tests
- For at least one customer environment: connect real PI, real Maximo.
- Run parity test (same scenario as simulator vs real).
- Document any divergences in `docs/simulator_parity.md`.

**DoD**: Parity report shows < 5% material divergence.

### S11.4 — Operator onboarding playbook
- Tag onboarding: UNS / PI AF / regex / manual.
- Template tuning workshop.
- First-week support runbook.

**DoD**: Playbook reviewed with pilot customer.

### S11.5 — Security review
- Threat model.
- Secrets handling audit.
- Pen-test (or self-pen-test using checklist).
- Data residency confirmation per tenant.

**DoD**: Findings closed or accepted with mitigation plan.

### S11.6 — Legal / contract
- Data processing agreement template.
- IP terms for learned overlays derived from customer data.

**DoD**: Template ready for pilot signing.
