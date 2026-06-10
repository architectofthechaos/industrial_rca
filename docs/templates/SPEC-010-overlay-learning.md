# SPEC-010: Overlay Learning

- **Status**: Draft
- **Owner**: gvishnu

## Purpose

Defines how the **learned overlay** layer in equipment-class templates updates from closed probes, and the rules that keep it from silently rewriting the curated core.

## Two-layer model

- **Curated core** (in `packages/templates/<class>.yaml`): standards-backed, slow-moving, PR-reviewed. Source of truth for failure modes, mechanisms, evidence recipes.
- **Learned overlay** (in `overlays` Postgres table): probe-derived. Stat updates auto-apply when sample size sufficient; structural changes require human approval.

Effective template at query time = curated core merged with applicable overlay records.

## Overlay record types

| Type | Allowed update | Approval |
|---|---|---|
| `prior_probability` | Updates `prior` field per failure mode, per site/service | Auto if `n >= 30` |
| `threshold_refinement` | Updates evidence-recipe threshold (e.g., vibration RMS limit) | Auto if `n >= 30` AND change < 30% |
| `site_variant_inheritance` | Marks asset variant (sour-service etc.) inherits from a parent template | Human |
| `emerging_cause` | Proposes a new cause not in standards | Human |
| `effectiveness_correlation` | Records which corrective actions worked | Auto-collected, reviewer-curated |
| `new_evidence_recipe` | Proposes new way to prove/disprove a failure mode | Human |
| `failure_mode_addition` | Proposes new ISO 14224-style code | Human; requires standards owner sign-off |

## Auto-apply rules

```python
def can_auto_apply(update: OverlayUpdate) -> bool:
    if update.type in {"site_variant_inheritance", "emerging_cause",
                       "new_evidence_recipe", "failure_mode_addition"}:
        return False
    if update.sample_size < 30:
        return False
    if update.type == "threshold_refinement" and abs(update.relative_change) > 0.30:
        return False
    return True
```

## Lifecycle

1. **Probe closes** with reviewer-approved cause map.
2. `overlay.propose_update` extracts candidate updates from probe outcome + reviewer edits.
3. Each candidate is scored (sample size, effect size, consistency with prior data).
4. Auto-applicable updates commit immediately; others go to the **template owner queue**.
5. Reviewer approves / rejects with rationale.
6. Approved updates are immediately effective for new probes. In-flight probes keep the template version they started with.

## Versioning

- Curated core: semver per template; pinned per probe.
- Overlay: each record has `valid_from` and supersedes-by chain; queries pick the latest applicable.

## Drift detection

- Quarterly review surfaces overlays that have drifted significantly from curated core (e.g., prior changed by > 2× over 6 months).
- Significant drift triggers a curated-core review.

## Rollback

- Every overlay update is reversible (`overlay.rollback_update(record_id)`).
- Rollback creates a new overlay record marking the prior superseded — never deletes history.
