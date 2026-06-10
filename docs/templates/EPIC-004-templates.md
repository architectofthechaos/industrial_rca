# EPIC-004: Equipment-class Templates (centrifugal pump)

**Goal**: Production-ready centrifugal pump template with curated core and overlay infrastructure.

**Duration**: Week 3–5

## Stories

### S4.1 — Template schema
- Pydantic `EquipmentTemplate` model.
- YAML loader with semver versioning.
- Validation: failure modes are ISO 14224, evidence recipes reference defined signal roles, priors sum to ≤ 1.

**DoD**: Schema implemented; centrifugal_pump.yaml v1 validates.

### S4.2 — Centrifugal pump curated core
- All 11 ISO 14224 failure modes for pumps.
- Evidence recipes per failure mode.
- Mechanisms referenced from API 571.
- Site-variant inheritance: sour-service, BFW, crude-charge.

**DoD**: Template covers all 4 scenarios in SPEC-008.

### S4.3 — Overlay storage
- Postgres `overlay_updates` table.
- Effective-template materialization (core merged with overlay).
- Versioning per [SPEC-010](SPEC-010-overlay-learning.md).

**DoD**: Overlay applied for one signal; effective template reflects the change.

### S4.4 — Templates MCP server
- `templates.load`, `templates.get_failure_modes`, `templates.get_method_template`.

**DoD**: Contract tests pass.

### S4.5 — Overlay learning engine
- `overlay.propose_update`, `overlay.commit_update`.
- Auto-apply rules per SPEC-010.
- Template owner review queue.

**DoD**: After closing a scenario probe, an auto-applicable update commits; a structural update enters the queue.
