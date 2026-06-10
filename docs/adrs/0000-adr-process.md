# ADR-0000: ADR process

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## What is an ADR

An Architecture Decision Record captures a single architecturally-significant decision, the context in which it was made, the alternatives considered, and the consequences.

## Rules

1. **Numbered sequentially.** `NNNN-short-title-kebab-case.md`. Never reuse a number.
2. **Immutable once accepted.** To change an accepted decision, write a new ADR that supersedes it. Add `Supersedes: ADR-XXXX` and `Superseded-by: ADR-YYYY` headers.
3. **Status values**: `Proposed` → `Accepted` → `Superseded` (or `Rejected`).
4. **Scope**: one decision per ADR. If you find yourself writing "and also...", split it.
5. **Audience**: an engineer joining the team in 6 months should be able to read an ADR and understand why we did what we did, without needing to interview anyone.

## Template

```markdown
# ADR-NNNN: <decision in active voice>

- Status: Proposed | Accepted | Superseded | Rejected
- Date: YYYY-MM-DD
- Deciders: <names>
- Supersedes: ADR-XXXX (if applicable)
- Superseded-by: ADR-YYYY (if applicable)

## Context

What problem are we solving? What constraints exist? What forces are in play?

## Decision

The chosen approach in active voice. "We will use X." Not "We might use X."

## Alternatives considered

For each: what it was, why we rejected it. Be specific.

## Consequences

Positive, negative, and neutral. What does this lock us into? What does it cost?

## References

Links to related ADRs, specs, external resources.
```

## When to write one

Write an ADR for any decision where, if reversed, would require non-trivial rework. Examples:

- Choice of workflow engine, agent framework, database
- Cross-cutting design patterns (canonical units, time handling)
- Interface contracts that multiple components depend on
- Security or operational policies

Do **not** write ADRs for implementation choices internal to a single component — those belong in the component's spec or README.
