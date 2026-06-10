# ADR-0009: Monorepo with uv workspaces

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

We have 10+ Python packages that share contracts and evolve together. We need fast local dev, single-PR cross-package changes, and CI that can build the whole graph.

## Decision

Single Git repo, organized as a **uv workspace** (https://docs.astral.sh/uv/concepts/projects/workspaces/).

- Top-level `pyproject.toml` declares workspace members.
- Each `packages/<name>/` has its own `pyproject.toml`.
- Shared dev deps (pytest, mypy, ruff, pre-commit) at the top level.
- `uv sync` installs everything in one venv.
- `uv run` from any package directory works.

CI matrix builds packages independently but lints and tests run on the full graph.

## Alternatives considered

**A. Poetry workspaces.** Rejected — uv is faster and is becoming the standard.

**B. Pants / Bazel monorepo build.** Rejected — overkill for current scale.

**C. Multi-repo.** Rejected — contract changes would require coordinated PRs across many repos, slowing iteration.

## Consequences

**Positive:** Fast iteration on contracts, single-PR changes, fast install via uv.

**Negative:** Repo gets large over time. Need clear ownership conventions inside the monorepo (CODEOWNERS).

## References

- uv: https://docs.astral.sh/uv/
