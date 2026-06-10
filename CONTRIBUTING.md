# Contributing

## Quick start

```bash
# Prereqs: uv (https://docs.astral.sh/uv/), docker, just (optional)
uv sync
docker compose -f infra/docker/compose.yaml up -d
uv run pytest
```

## Branching

- `main` is always green. CI gates all PRs.
- Feature branches: `feat/<epic>-<slug>` (e.g., `feat/epic-012-mar-seed`).
- Bugfix: `fix/<short-description>`.

## Commits

Conventional Commits required: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## PR checklist

- [ ] Linked to a story in an EPIC doc, or to an issue.
- [ ] Contract changes (`packages/contracts`) flagged in PR title.
- [ ] If touching an ADR-locked decision, ADR updated or superseded.
- [ ] Tests added or updated; CI green.
- [ ] Eval scenarios unchanged or intentionally updated with rationale.

## Code style

- Python 3.12+.
- Ruff (formatter + linter) enforced.
- Mypy strict mode in `packages/contracts`; gradual elsewhere.
- Pydantic v2 strict everywhere.

## Adding a new ADR

```bash
cp docs/adrs/0000-adr-process.md docs/adrs/00XX-<slug>.md
# edit; submit as PR; merge once Accepted
```

## Adding a new connector

1. Update [SPEC-002](docs/connectors/SPEC-002-mcp-tool-contracts.md) with the new tools.
2. Add Pydantic models to `packages/contracts`.
3. Build the simulator first (in `packages/simulators/<name>/`).
4. Build the production connector with the same MCP contract.
5. Add contract tests.

## Reviewing PRs

- Contract changes need at least one review from a contracts owner (`CODEOWNERS`).
- ADR changes need consensus from listed deciders.
- Template changes (`packages/templates/`) need a template owner review.
