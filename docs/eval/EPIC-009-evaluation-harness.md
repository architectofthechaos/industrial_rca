# EPIC-009: Evaluation Harness

**Goal**: Frozen scenarios become regression tests; every release scores against the catalog.

**Duration**: Week 10–11

## Stories

### S9.1 — Eval runner
- Spin up full stack against simulators in CI.
- Run each scenario in [SPEC-008](../simulators/SPEC-008-scenario-catalog.md) as a probe.
- Auto-respond to HITL gates with scenario-defined responses.

**DoD**: All 4 MVP scenarios run automatically in < 30 minutes.

### S9.2 — Scoring
- Top candidate match.
- Confidence threshold.
- Root cause semantic similarity (using a frozen reference embedding model).
- Corrective action overlap.
- Composite score per scenario; aggregate per release.

**DoD**: Scores emitted as JSON + Markdown summary.

### S9.3 — CI gating
- PRs that regress any scenario score by > 5% blocked.
- Reports posted as PR comment.

**DoD**: A deliberate regression in a template change blocks merge.

### S9.4 — Replay harness
- Record probe Temporal histories.
- Replay against new code to detect determinism regressions.

**DoD**: Stored histories replay cleanly across at least 3 successive releases.

### S9.5 — Expand scenarios
- Add 6 more scenarios across the 4 reference assets to reach 10 total for MVP gate.

**DoD**: 10 scenarios, all passing.
